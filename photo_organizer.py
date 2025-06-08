#!/usr/bin/env python3

import os
import logging
import subprocess
import json
from datetime import datetime
from pathlib import Path
import re
import shutil
from typing import Optional
import hashlib

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(message)s'  # Simplified format, no timestamp (it's added by the system)
)
logger = logging.getLogger(__name__)

# Configuration
INPUT_DIR = "./input"
OUTPUT_DIR = "./output"
UNPROCESSED_DIR = "./output/unprocessed"  # Directory for unprocessed files
UNREALISTIC_DATES = ['1970-01-01', '1980-01-01']  # Default dates often set by cameras/systems
MIN_VALID_YEAR = 1985  # Earliest acceptable year for photos

# Shutter count EXIF tags for different cameras
SHUTTER_COUNT_TAGS = [
    'ShutterCount',            # Common (Nikon)
    'ImageCount',               # Some cameras
    'ShutterCountValue',        # Some Nikon
    'SonyImageCount',           # Sony
    'ShutterCounter',           # Some Canon
    'InternalSerialNumber',     # Some Canon (last digits)
    'ImageNumber'               # Alternative
]

# Image file extensions
JPG_EXTENSIONS = {
    '.jpg', 
    '.jpeg'
}

RAW_EXTENSIONS = {
    '.arw',   # Sony Raw
    '.cr2',   # Canon Raw
    '.nef',   # Nikon Raw
    '.heic'   # iPhone
}

# Additional image extensions (typically not photos)
OTHER_IMAGE_EXTENSIONS = {
    '.gif',   # Animated graphics
    '.png',   # Often used for logos, icons, graphics
    '.bmp'    # Bitmap images, often not photos
}

# Icon file extensions
ICON_EXTENSIONS = {
    '.ico',   # Windows icons
    '.icns'   # macOS icons
}

# Vector graphics extensions
VECTOR_EXTENSIONS = {
    '.svg',   # Scalable Vector Graphics
    '.eps',   # Encapsulated PostScript
    '.ai'     # Adobe Illustrator
}

# TIFF files require special handling
TIFF_EXTENSIONS = {
    '.tif', 
    '.tiff'
}

# Combine all supported extensions
SUPPORTED_EXTENSIONS = (
    JPG_EXTENSIONS.union(RAW_EXTENSIONS)
    .union(OTHER_IMAGE_EXTENSIONS)
    .union(ICON_EXTENSIONS)
    .union(VECTOR_EXTENSIONS)
    .union(TIFF_EXTENSIONS)
)

def get_base_output_dir(file_extension):
    """Determine the base output directory based on file type."""
    if file_extension.lower() in JPG_EXTENSIONS:
        return Path(OUTPUT_DIR) / "jpg"
    elif file_extension.lower() in RAW_EXTENSIONS:
        return Path(OUTPUT_DIR) / "raw"
    elif file_extension.lower() in OTHER_IMAGE_EXTENSIONS:
        return Path(OUTPUT_DIR) / "other"
    else:
        return None

def ensure_directories_exist():
    """Create input and output directories if they don't exist."""
    directories = [
        INPUT_DIR,
        Path(OUTPUT_DIR) / "jpg",
        Path(OUTPUT_DIR) / "raw",
        Path(OUTPUT_DIR) / "other",
        Path(OUTPUT_DIR) / "screenshots",
        Path(OUTPUT_DIR) / "non_camera_images" / "icons",
        Path(OUTPUT_DIR) / "non_camera_images" / "vector",
        Path(OUTPUT_DIR) / "non_camera_images" / "graphics",
        UNPROCESSED_DIR
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)

def get_shutter_count(file_path):
    """
    Extract shutter count from EXIF data using exiftool.
    Returns None if not found.
    """
    try:
        # Create command with all possible shutter count tags
        tag_args = []
        for tag in SHUTTER_COUNT_TAGS:
            # For exiftool, we need to format the tag differently
            formatted_tag = tag.replace(' ', ':')
            tag_args.extend(['-' + formatted_tag])
        
        cmd = ['exiftool', '-j'] + tag_args + [str(file_path)]
        logger.debug(f"Executing exiftool command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.debug(f"Exiftool returned error: {result.stderr}")
            return None

        data = json.loads(result.stdout)
        if not data:
            logger.debug("No EXIF data found")
            return None

        # Try each possible shutter count tag
        for tag in SHUTTER_COUNT_TAGS:
            count = data[0].get(tag)
            logger.debug(f"Checking tag {tag}: {count}")
            if count:
                # Try to extract number if it's a string (like in serial numbers)
                if isinstance(count, str):
                    matches = re.findall(r'\d+', count)
                    if matches:
                        count = matches[-1]  # Take the last number group
                try:
                    return int(count)
                except (ValueError, TypeError):
                    continue
        
        logger.debug("No shutter count found in any tag")
        return None
    except Exception as e:
        logger.error(f"Error reading shutter count from {file_path}: {str(e)}")
        return None

def get_exif_creation_date(file_path):
    """
    Extract creation date from EXIF data using exiftool.
    Returns None if date is unrealistic or not found.
    """
    try:
        # Try to get CreateDate, if not available, try DateTimeOriginal
        cmd = ['exiftool', '-CreateDate', '-DateTimeOriginal', '-j', file_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.warning(f"Failed to read EXIF data for {file_path}")
            return None

        data = json.loads(result.stdout)
        if not data:
            return None

        # Try different date fields
        date_str = data[0].get('CreateDate') or data[0].get('DateTimeOriginal')
        
        if not date_str:
            return None

        # Check for invalid date strings
        if '0000:00:00' in date_str or '0000-00-00' in date_str:
            logger.debug(f"Invalid date string in EXIF: {date_str}")
            return None

        # Convert EXIF date format to datetime
        # Typical format: "2023:12:13 15:30:00"
        date_str = date_str.replace(':', '-', 2)  # Replace only first two colons
        
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            logger.debug(f"Could not parse date string: {date_str}")
            return None
        
        # Check if date is realistic
        if dt.strftime('%Y-%m-%d') in UNREALISTIC_DATES:
            logger.warning(f"Unrealistic date found in EXIF: {dt} for {file_path}")
            return None
            
        # Additional validation for year
        if dt.year < MIN_VALID_YEAR or dt.year > datetime.now().year:
            logger.debug(f"Year {dt.year} outside valid range ({MIN_VALID_YEAR}-{datetime.now().year})")
            return None
            
        return dt
    except Exception as e:
        logger.error(f"Error reading EXIF data from {file_path}: {str(e)}")
        return None

def extract_date_from_filename(filename: str) -> Optional[datetime]:
    """
    Try to extract date from filename using various patterns.
    Returns None if no valid date pattern is found.

    Handles formats like:
    - YYYYMMDD_HHMMSS
    - YYYY-MM-DD_HH-MM-SS
    - YYYY-MM-DD-HH-MM-SS
    - YYYY_MM_DD_HH_MM_SS
    - DD-MM-YYYY_HHMMSS
    - YYYYMMDDHHMMSS
    - YYYY-MM-DD
    - DD-MM-YYYY
    """
    # Ensure current_year is always defined
    current_year: int = datetime.now().year

    # Validate input
    if not filename or not isinstance(filename, str):
        logger.debug(f"Invalid filename: {filename}")
        return None

    # Date patterns to match
    patterns = [
        # Full datetime patterns
        r'(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})',  # YYYY-MM-DD-HH-MM-SS
        r'(\d{2})-(\d{2})-(\d{4})-(\d{2})-(\d{2})-(\d{2})',  # DD-MM-YYYY-HH-MM-SS
        r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})',      # YYYYMMDD_HHMMSS
        r'(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})',  # YYYY-MM-DD_HH-MM-SS
        r'(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})',  # YYYY_MM_DD_HH_MM_SS
        r'(\d{2})-(\d{2})-(\d{4})_(\d{2})(\d{2})(\d{2})',    # DD-MM-YYYY_HHMMSS
        r'(\d{8})-(\d{6})',                                  # YYYYMMDD-HHMMSS
        r'(\d{12})',                                         # YYYYMMDDHHMMSS
        
        # Date-only patterns
        r'(\d{4})-(\d{2})-(\d{2})',                          # YYYY-MM-DD
        r'(\d{2})-(\d{2})-(\d{4})'                           # DD-MM-YYYY
    ]

    # Try each pattern
    for pattern in patterns:
        match = re.search(pattern, filename)
        
        if match:
            try:
                groups = match.groups()
            except Exception as e:
                logger.debug(f"Error extracting groups from filename {filename}: {e}")
                continue

            try:
                # Initialize variables with default values
                year = month = day = hour = minute = second = None

                # Handle full datetime patterns
                if len(groups) == 6:  # Full datetime pattern
                    if len(groups[0]) == 4:  # YYYY-MM-DD-HH-MM-SS
                        year, month, day, hour, minute, second = groups
                    else:  # DD-MM-YYYY-HH-MM-SS
                        day, month, year, hour, minute, second = groups
                
                # Handle YYYYMMDDHHMMSS format
                elif len(groups) == 1:  # YYYYMMDDHHMMSS format
                    date_str = groups[0]
                    year = date_str[:4]
                    month = date_str[4:6]
                    day = date_str[6:8]
                    hour = date_str[8:10]
                    minute = date_str[10:12]
                    second = "00"
                
                # Handle YYYYMMDD-HHMMSS format
                elif len(groups) == 2:  # YYYYMMDD-HHMMSS format
                    date_str, time_str = groups
                    year = date_str[:4]
                    month = date_str[4:6]
                    day = date_str[6:8]
                    hour = time_str[:2]
                    minute = time_str[2:4]
                    second = time_str[4:6]
                
                # Handle date-only patterns
                elif len(groups) == 3:
                    if len(groups[0]) == 4:  # YYYY-MM-DD
                        year, month, day = groups
                        hour, minute, second = "00", "00", "00"
                    else:  # DD-MM-YYYY
                        day, month, year = groups
                        hour, minute, second = "00", "00", "00"
            except Exception as e:
                logger.debug(f"Error processing date groups from filename {filename}: {e}")
                continue

            # Explicit type conversion and validation
            try:
                # Ensure all components are strings before conversion
                year = str(year).strip()
                month = str(month).strip()
                day = str(day).strip()
                hour = str(hour).strip() or "00"
                minute = str(minute).strip() or "00"
                second = str(second).strip() or "00"
                
                # Convert to integers
                year_int = int(year)
                month_int = int(month)
                day_int = int(day)
                hour_int = int(hour)
                minute_int = int(minute)
                second_int = int(second)
                
                # Basic validation
                if not (MIN_VALID_YEAR <= year_int <= current_year):
                    logger.debug(f"Year {year_int} outside valid range ({MIN_VALID_YEAR}-{current_year})")
                    continue
                if not (1 <= month_int <= 12):
                    continue
                if not (1 <= day_int <= 31):
                    continue
                if not (0 <= hour_int <= 23):
                    continue
                if not (0 <= minute_int <= 59):
                    continue
                if not (0 <= second_int <= 59):
                    continue
                
                # Create datetime object
                dt = datetime(year_int, month_int, day_int, hour_int, minute_int, second_int)
                
                # Additional validation for unrealistic dates
                if dt.strftime('%Y-%m-%d') in UNREALISTIC_DATES:
                    logger.debug(f"Unrealistic date found in filename: {dt.strftime('%Y-%m-%d')}")
                    continue
                
                return dt
            
            except (ValueError, TypeError) as e:
                logger.debug(f"Error parsing date from filename {filename}: {e}")
                continue
    
    return None

def to_camel_case(s):
    """
    Convert a string to camel case, preserving model numbers.
    Handles various input formats like:
    - NIKONCORPORATIONNIKOND5100
    - Nikon Corporation Nikon D5100
    - nikon-corporation-nikon-d5100
    """
    # Remove non-alphanumeric characters and split
    words = re.findall(r'[a-zA-Z]+|\d+', s)
    
    # Capitalize each word except the first
    if not words:
        return s
    
    # Special case for Apple/iPhone
    if any('apple' in word.lower() for word in words) or any('iphone' in word.lower() for word in words):
        return 'Apple' + 'iPhone' + ''.join(word for word in words[2:])
    
    # Capitalize corporation names, keep model numbers as-is
    camel_case = words[0].capitalize()
    for word in words[1:]:
        # Check if the word is purely alphabetic (corporation name)
        if word.isalpha():
            camel_case += word.capitalize()
        else:
            # Preserve model numbers and other numeric parts
            camel_case += word
    
    return camel_case

def clean_make(make):
    """Clean up camera make string."""
    if not make:
        return ''
        
    # Hardcoded make names
    if make.lower() == 'sonyericsson':
        return 'SonyEricsson'
    elif make.lower() in ['pentaxcorporation', 'pentax', 'pentax corporation']:
        return 'Pentax'
    elif make.lower() in ['nikoncorporation', 'nikon', 'nikon corporation']:
        return 'Nikon'
    
    # Remove 'Corporation' if present
    if 'corporation' in make.lower():
        make = make.replace('Corporation', '').strip()
    
    # Remove spaces, dashes, and special characters
    make = re.sub(r'[^a-zA-Z0-9]', '', make)
    
    # Convert to camel case if not already hardcoded
    if make not in ['SonyEricsson', 'Pentax', 'Nikon', 'Sony', 'Apple']:
        make = to_camel_case(make)
    
    return make

def clean_model(model, make):
    """Clean up camera model string."""
    if not model:
        return ''
    
    # Remove make from model if it's included
    if make and model.lower().startswith(make.lower()):
        model = model[len(make):].strip()
    
    # Replace spaces with dashes
    model = model.replace(' ', '-')
    
    # Replace forward slashes and backslashes with dashes
    model = model.replace('/', '-').replace('\\', '-')
    
    # Replace other potentially problematic characters
    model = model.replace(',', '_').replace('(', '').replace(')', '')
    
    # Hardcoded rules for specific cameras
    if make == 'Nikon':
        # If it's a D series camera, ensure format is "NIKON-D####"
        if re.search(r'D\d{3,4}', model, re.IGNORECASE):
            d_number = re.search(r'D\d{3,4}', model, re.IGNORECASE).group(0)
            return f"NIKON-{d_number.upper()}"
        # For Z series
        elif re.search(r'Z\d{1,2}', model, re.IGNORECASE):
            z_number = re.search(r'Z\d{1,2}', model, re.IGNORECASE).group(0)
            return f"NIKON-{z_number.upper()}"
    elif make == 'Sony':
        if model.upper().startswith('ILCE'):
            return model.upper()  # Keep Sony model numbers in uppercase
    elif make == 'Canon':
        # For EOS models
        if 'EOS' in model.upper():
            return model.upper()
    
    return model

def get_camera_info(file_path):
    """
    Extract camera make and model from EXIF data.
    Returns tuple (make, model) or (None, None) if not found.
    
    Includes hardcoded rules for specific cameras.
    """
    try:
        # Run exiftool and get JSON output
        result = subprocess.run(
            ['exiftool', '-j', '-Make', '-Model', str(file_path)],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse JSON output
        exif_data = json.loads(result.stdout)[0]
        
        # Get make and model
        make = exif_data.get('Make', '').strip()
        model = exif_data.get('Model', '').strip()
        
        # Clean up make and model
        make = clean_make(make)
        model = clean_model(model, make)
        
        return make, model
        
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error getting camera info for {file_path}: {str(e)}")
        return '', ''

def is_likely_photo(file_path):
    """
    Determine if an image is likely a photo based on multiple criteria.
    
    Checks:
    - Camera metadata
    - Image dimensions
    - Potential non-photo indicators
    """
    try:
        # Use ExifTool to get comprehensive image information
        cmd = ['exiftool', 
               '-FileType', 
               '-Make', 
               '-Model', 
               '-Software', 
               '-ImageWidth', 
               '-ImageHeight', 
               '-ColorSpace',
               '-Compression',
               '-j', 
               str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.warning(f"ExifTool failed for {file_path}")
            return False

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse ExifTool output for {file_path}")
            return False

        if not data or len(data) == 0:
            logger.warning(f"No metadata found for {file_path}")
            return False

        # Extract relevant metadata
        metadata = data[0]
        
        # Check for camera metadata
        make = metadata.get('Make', '').strip()
        model = metadata.get('Model', '').strip()
        
        # Check image dimensions
        width = int(metadata.get('ImageWidth', 0))
        height = int(metadata.get('ImageHeight', 0))
        
        # Check software and potential non-photo indicators
        software = metadata.get('Software', '').lower()
        color_space = metadata.get('ColorSpace', '').lower()
        compression = metadata.get('Compression', '').lower()
        
        # Non-photo indicators
        non_photo_software = [
            'photoshop',
            'illustrator',
            'inkscape',
            'gimp',
            'paint',
            'sketch',
            'figma',
            'xd',
            'canva'
        ]
        
        # Criteria for a likely photo
        is_photo = (
            # Has camera metadata
            (make and model) or 
            # Large enough image with reasonable dimensions
            (width > 1000 and height > 1000) or 
            # Typical photo color spaces
            (color_space in ['srgb', 'adobe rgb', 'prophoto rgb'])
        )
        
        # Exclude if clear non-photo indicators are present
        if is_photo:
            if any(indicator in software.lower() for indicator in non_photo_software):
                return False
        
        return is_photo
    
    except Exception as e:
        logger.error(f"Error checking if image is a photo {file_path}: {str(e)}")
        return False

def detect_image_type(file_path):
    """
    Detect the type of image and categorize it.
    
    Returns:
    - 'screenshot' if it's a screenshot
    - 'non_camera_image' for other non-camera images
    - None if it's a camera photo
    """
    try:
        # Get metadata using exiftool
        cmd = ['exiftool', '-j', '-Software', '-ColorSpace', '-Compression',
               '-ScreenCaptureType', '-FileType', '-ImageWidth', '-ImageHeight',
               '-PNG:ColorType', '-PNG:BitDepth', str(file_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.debug(f"Error getting metadata: {result.stderr}")
            return None
            
        data = json.loads(result.stdout)
        if not data:
            return None
            
        metadata = data[0]
        
        # Convert metadata values to strings, handling potential float values
        software = str(metadata.get('Software', '')).lower()
        color_space = str(metadata.get('ColorSpace', '')).lower()
        compression = str(metadata.get('Compression', '')).lower()
        file_type = str(metadata.get('FileType', '')).lower()
        
        # Get PNG-specific metadata
        png_color_type = metadata.get('PNG:ColorType', '')
        png_bit_depth = metadata.get('PNG:BitDepth', '')
        width = metadata.get('ImageWidth', 0)
        height = metadata.get('ImageHeight', 0)

        # Check for screenshot indicators
        if any(x in software for x in ['screen', 'screenshot']):
            return 'screenshot'

        # Additional checks for PNG screenshots
        if file_type == 'png':
            # Most screenshots are RGB/RGBA PNGs with 8-bit depth
            # PNG:ColorType values: 0=Grayscale, 2=RGB, 3=Palette, 4=Grayscale+Alpha, 6=RGB+Alpha
            if ((png_color_type in [2, 6] or png_color_type in ['RGB', 'RGB+Alpha']) and 
                (png_bit_depth == 8 or png_bit_depth == '8') and
                width >= 800):  # Common screen width threshold
                return 'screenshot'

        # List of software names that indicate non-photo images
        non_photo_software = [
            'photoshop',
            'illustrator',
            'inkscape',
            'gimp',
            'paint',
            'sketch',
            'figma',
            'xd',
            'canva'
        ]
        
        # Check for software that indicates non-photo images
        if any(indicator in software for indicator in non_photo_software):
            return 'non_camera_image'
            
        return None
        
    except Exception as e:
        logger.error(f"Error detecting image type for {file_path}: {str(e)}")
        return None

def is_duplicate_file(file1_path: Path, file2_path: Path) -> bool:
    """
    Check if two files are identical by comparing size and content.
    
    Args:
        file1_path: Path to first file
        file2_path: Path to second file
        
    Returns:
        bool: True if files are identical, False otherwise
    """
    logger.debug(f"Comparing files for duplicates:")
    logger.debug(f"  File 1: {file1_path}")
    logger.debug(f"  File 2: {file2_path}")
    
    if not (file1_path.exists() and file2_path.exists()):
        logger.debug("  One or both files do not exist")
        return False
        
    # First check if file sizes match
    size1 = file1_path.stat().st_size
    size2 = file2_path.stat().st_size
    logger.debug(f"  Size comparison: {size1} vs {size2}")
    if size1 != size2:
        logger.debug("  Files have different sizes")
        return False
        
    # Compare file contents using SHA-256 hash
    BUFFER_SIZE = 65536  # 64kb chunks
    
    sha256_1 = hashlib.sha256()
    sha256_2 = hashlib.sha256()
    
    try:
        with open(file1_path, 'rb') as f1:
            while True:
                data = f1.read(BUFFER_SIZE)
                if not data:
                    break
                sha256_1.update(data)
                
        with open(file2_path, 'rb') as f2:
            while True:
                data = f2.read(BUFFER_SIZE)
                if not data:
                    break
                sha256_2.update(data)
                
        hash1 = sha256_1.digest()
        hash2 = sha256_2.digest()
        logger.debug(f"  Hash comparison: {hash1.hex()} vs {hash2.hex()}")
        are_identical = hash1 == hash2
        logger.debug(f"  Files are {'identical' if are_identical else 'different'}")
        return are_identical
    except Exception as e:
        logger.error(f"Error comparing files: {str(e)}")
        return False

def process_photo(file_path):
    """
    Process a photo file, organizing it based on its metadata and type.
    
    Handles different image types:
    - Camera photos (with EXIF data)
    - Screenshots
    - Other non-camera images
    - Icons (.ico, .icns)
    - Vector graphics (.svg, .eps, .ai)
    """
    try:
        file_path = Path(file_path)
        if not file_path.is_file():
            return False

        # Get file extension and check if it's supported
        file_extension = file_path.suffix.lower()
        if file_extension not in SUPPORTED_EXTENSIONS:
            return False

        # Detect image type
        image_type = detect_image_type(file_path)
        
        # Extract date from EXIF or filename
        file_date = extract_date(file_path)
        
        # Get camera information for photos
        camera_make, camera_model = get_camera_info(file_path)

        if image_type == 'screenshot':
            # Process screenshot
            target_dir = Path(OUTPUT_DIR) / "screenshots"
            if file_date:
                target_dir = organize_by_date(target_dir, file_date)
            
            # For screenshots, use timestamp prefix with cleaned original name
            timestamp_prefix = file_date.strftime('%Y%m%d-%H%M%S') if file_date else ""
            original_name = Path(file_path).stem
            
            # Remove any existing timestamps from the original name
            if timestamp_prefix:
                timestamp_info = extract_timestamp_from_filename(original_name)
                if timestamp_info:
                    _, original_name = timestamp_info
                
                # Pad any numbers in the original name
                original_name = pad_numbers_in_filename(original_name)
                new_filename = f"{timestamp_prefix}-{original_name}{file_extension}"
            else:
                new_filename = pad_numbers_in_filename(file_path.name)
            
            target_dir, unique_filename, is_duplicate = generate_unique_filename(
                target_dir, new_filename, file_path, use_dashes=True
            )
            
            if is_duplicate:
                logger.info(f"Duplicate screenshot found, skipping: {file_path}")
                os.remove(file_path)  # Remove duplicate file
                return True
                
            target_path = target_dir / unique_filename
            shutil.copy2(file_path, target_path)
            os.remove(file_path)  # Remove original file after successful copy
            logger.info(f"Moved screenshot to: {target_path}")
            return True

        elif image_type:  # Non-camera images (icons, vectors, graphics)
            # Determine the specific non-camera image directory
            if file_extension in ICON_EXTENSIONS:
                base_dir = Path(OUTPUT_DIR) / "non_camera_images" / "icons"
            elif file_extension in VECTOR_EXTENSIONS:
                base_dir = Path(OUTPUT_DIR) / "non_camera_images" / "vector"
            else:
                base_dir = Path(OUTPUT_DIR) / "non_camera_images" / "graphics"

            # Try to extract timestamp from filename if no EXIF date
            if not file_date:
                timestamp_info = extract_timestamp_from_filename(file_path.name)
                if timestamp_info:
                    file_date, original_name = timestamp_info
                else:
                    original_name = Path(file_path).stem
            else:
                # If we have a file_date, check if original name has timestamp to remove
                timestamp_info = extract_timestamp_from_filename(file_path.name)
                if timestamp_info:
                    _, original_name = timestamp_info
                else:
                    original_name = Path(file_path).stem

            # Pad any numbers in the original name
            original_name = pad_numbers_in_filename(original_name)

            # Create new filename with timestamp at the start
            if file_date:
                new_name = f"{file_date.strftime('%Y%m%d-%H%M%S')}-{original_name}{file_extension}"
                target_dir = organize_by_date(base_dir, file_date)
            else:
                new_name = pad_numbers_in_filename(file_path.name)
                target_dir = base_dir
                
            target_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate unique filename
            target_dir, unique_filename, is_duplicate = generate_unique_filename(
                target_dir, new_name, file_path, use_dashes=True
            )
            
            if is_duplicate:
                logger.info(f"Duplicate non-camera image found, skipping: {file_path}")
                os.remove(file_path)  # Remove duplicate file
                return True
                
            target_path = target_dir / unique_filename
            shutil.copy2(file_path, target_path)
            os.remove(file_path)  # Remove original file after successful copy
            logger.info(f"Moved non-camera image to: {target_path}")
            return True

        else:  # Regular photos - keep existing naming convention
            if not file_date:
                logger.warning(f"No valid date found for {file_path}")
                return move_to_unprocessed(file_path)

            # Determine base output directory based on file type
            base_output_dir = get_base_output_dir(file_extension)
            if not base_output_dir:
                logger.warning(f"Unsupported file type for organizing: {file_extension}")
                return move_to_unprocessed(file_path)

            # Generate new filename using existing photo naming convention
            new_filename = generate_filename(file_path, file_date, camera_make, camera_model)

            # Create directories with YYYY/YYYY-MM/YYYY-MM-DD structure
            target_dir = organize_by_date(base_output_dir, file_date)

            # Check if this exact file already exists in the target directory
            target_dir, unique_filename, is_exact_duplicate = generate_unique_filename(
                target_dir, 
                new_filename, 
                file_path,
                is_duplicate=True
            )
            
            if is_exact_duplicate:
                logger.info(f"Deleted duplicate file: '{file_path}' (identical to '{target_dir / unique_filename}')")
                os.remove(file_path)
            else:
                # Copy the file and preserve metadata
                shutil.copy2(file_path, target_dir / unique_filename)
                os.remove(file_path)
                logger.info(f"Processed: {file_path} -> {target_dir / unique_filename}")
            
            return True

    except Exception as e:
        logger.error(f"Error processing {file_path}: {str(e)}")
        return move_to_unprocessed(file_path)

def move_to_unprocessed(file_path):
    """
    Move an unprocessed file to the unprocessed directory.
    All files will be placed in a single folder with formatted names.
    
    Args:
        file_path: Path object of the file to move
    
    Returns:
        bool: True if move was successful, False otherwise
    """
    try:
        # Get the filename only
        original_name = Path(file_path).name
        name, ext = os.path.splitext(original_name)
        
        # Format the filename: lowercase and dashes
        formatted_name = name.lower().replace(' ', '-')
        # Clean up the filename
        formatted_name = re.sub(r'-+', '-', formatted_name).strip('-')
        new_filename = f"{formatted_name}{ext.lower()}"
        
        # Create target path
        target_path = Path(UNPROCESSED_DIR) / new_filename
        
        # Ensure unique filename - we don't check for duplicates in unprocessed dir
        target_dir, unique_filename, _ = generate_unique_filename(
            UNPROCESSED_DIR, 
            new_filename, 
            source_path=file_path,
            use_dashes=True, 
            is_duplicate=False  # Don't check for duplicates in unprocessed dir
        )
        target_path = target_dir / unique_filename
        
        # Move the file
        shutil.move(str(file_path), str(target_path))
        logger.info(f"Moved unprocessed file to: {target_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error moving unprocessed file {file_path}: {str(e)}")
        return False

def cleanup_directory(directory_path):
    """
    Clean up a directory by handling unprocessed files, removing hidden files,
    and removing empty directories recursively (except for the inbox directory).
    - Removes hidden files
    - Moves unprocessable files to unprocessed directory
    - Preserves supported image files in place
    - Removes empty directories
    
    Args:
        directory_path: Path object representing the directory to clean
    
    Returns:
        bool: True if directory was removed (either empty or after cleaning)
    """
    try:
        # Convert to Path object if it's not already
        dir_path = Path(directory_path)
        
        # Don't process the inbox directory
        if str(dir_path) == INPUT_DIR:
            return False
        
        # First check if directory is already empty
        try:
            contents = list(dir_path.iterdir())
            if not contents:
                if str(dir_path) != INPUT_DIR:
                    dir_path.rmdir()
                    return True
                return False
        except Exception as e:
            logger.error(f"Error accessing {dir_path}: {str(e)}")
            return False
        
        # Process all subdirectories first
        for item in contents:
            if item.is_dir():
                cleanup_directory(item)
        
        # Check directory contents again after processing subdirectories
        try:
            contents = list(dir_path.iterdir())
            if not contents and str(dir_path) != INPUT_DIR:
                dir_path.rmdir()
                return True
        except Exception as e:
            logger.error(f"Error accessing {dir_path}: {str(e)}")
            return False
        
        has_remaining_files = False
        # Process files: remove hidden files, move unprocessable files
        for item in contents:
            if item.is_file():
                if item.name.startswith('.') or item.name.startswith('~$'):
                    # Remove hidden files
                    try:
                        item.unlink()
                    except Exception as e:
                        logger.error(f"Could not remove {item}: {str(e)}")
                        has_remaining_files = True
                else:
                    ext = item.suffix.lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        # Keep supported image files in place
                        has_remaining_files = True
                    else:
                        # Move unprocessable files to unprocessed directory
                        if not move_to_unprocessed(item):
                            has_remaining_files = True
        
        # Final check if directory is empty
        try:
            contents = list(dir_path.iterdir())
            if not contents and str(dir_path) != INPUT_DIR:
                dir_path.rmdir()
                return True
        except Exception as e:
            logger.error(f"Error accessing {dir_path}: {str(e)}")
            
        return not has_remaining_files
        
    except Exception as e:
        logger.error(f"Error cleaning {directory_path}: {str(e)}")
        return False

def update_exif_date(file_path, date_time):
    """
    Update EXIF date fields in the image file.
    
    Args:
        file_path: Path to the image file
        date_time: datetime object with the correct date/time
    
    Returns:
        bool: True if update was successful, False otherwise
    """
    try:
        # Format datetime for exiftool (YYYY:MM:DD HH:MM:SS)
        date_str = date_time.strftime('%Y:%m:%d %H:%M:%S')
        
        # Get original file modification time
        original_mtime = os.path.getmtime(file_path)
        
        # Update both CreateDate and DateTimeOriginal
        cmd = [
            'exiftool',
            '-CreateDate=' + date_str,
            '-DateTimeOriginal=' + date_str,
            '-overwrite_original',  # Don't create backup files
            str(file_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"Failed to update EXIF data for {file_path}: {result.stderr}")
            return False
            
        # Restore original modification time
        os.utime(file_path, (original_mtime, original_mtime))
        
        logger.info(f"Updated EXIF date to {date_str} for {file_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error updating EXIF data for {file_path}: {str(e)}")
        return False

def extract_date(file_path):
    """
    Extract date from EXIF or filename. If EXIF date is invalid but filename
    has a valid date, update the EXIF data.
    
    Returns None if no valid date is found.
    """
    # First try EXIF
    creation_date = get_exif_creation_date(file_path)
    
    if not creation_date:
        # Try filename if EXIF failed
        filename = os.path.basename(file_path)
        creation_date = extract_date_from_filename(filename)
        
        # If we got a valid date from filename and this is a photo file,
        # update the EXIF data
        if creation_date:
            file_ext = os.path.splitext(file_path)[1].lower()
            is_photo = file_ext in JPG_EXTENSIONS or file_ext in RAW_EXTENSIONS
            
            if is_photo:
                logger.info(f"Found valid date in filename but invalid EXIF for {file_path}")
                if update_exif_date(file_path, creation_date):
                    logger.info(f"Successfully updated EXIF data for {file_path}")
                else:
                    logger.warning(f"Failed to update EXIF data for {file_path}, but proceeding with filename date")
    
    return creation_date

def generate_filename(file_path, file_date, camera_make, camera_model):
    """
    Generate a new filename based on the file's date, camera make, and model.
    Format: YYYYMMDD-HHMMSS_[ShutterCount]_[CameraMake-Model].[ext]
    """
    # Get the file extension and convert jpeg to jpg
    ext = file_path.suffix.lower()
    if ext == '.jpeg':
        ext = '.jpg'

    # Format the date part
    date_part = file_date.strftime('%Y%m%d-%H%M%S')

    # Get shutter count and pad to 6 digits
    shutter_count = get_shutter_count(file_path)
    shutter_part = f"_{shutter_count:06d}" if shutter_count is not None else ""

    # Clean and format camera info
    camera_part = ""
    if camera_make or camera_model:
        make_model = []
        if camera_make:
            make_model.append(clean_make(camera_make))
        if camera_model:
            make_model.append(clean_model(camera_model, camera_make if camera_make else ""))
        camera_part = f"_{'-'.join(make_model)}"

    # Combine all parts
    filename = f"{date_part}{shutter_part}{camera_part}{ext}"
    
    return filename

def pad_numbers_in_filename(filename: str) -> str:
    """
    Pad any numbers in the filename to be 3 digits long.
    Handles numbers that come after - or _ characters.
    Skip padding for camera model numbers.
    
    Args:
        filename: Original filename to process
        
    Returns:
        Filename with padded numbers
    """
    # Split filename and extension
    name, ext = os.path.splitext(filename)
    
    # Split the filename into parts by underscores
    parts = name.split('_')
    
    # Process each part separately
    for i, part in enumerate(parts):
        # Skip padding for the camera model part (last part)
        if i == len(parts) - 1 and '-' in part:
            continue
            
        # For other parts, pad numbers after - or at the start
        subparts = part.split('-')
        for j, subpart in enumerate(subparts):
            # Only pad if it's a pure number
            if subpart.isdigit():
                subparts[j] = subpart.zfill(3)
        parts[i] = '-'.join(subparts)
    
    # Rejoin the parts and add extension
    return '_'.join(parts) + ext

def generate_unique_filename(base_path, proposed_filename, source_path=None, use_dashes=False, is_duplicate=False):
    """
    Generate a unique filename by adding a 3-digit counter if a file already exists.
    For duplicates, they will be deleted if they are exact matches.
    
    Args:
        base_path (str or Path): Directory where the file will be saved
        proposed_filename (str): Original proposed filename
        source_path (Path): Path to the source file being processed
        use_dashes (bool): If True, use dashes instead of underscores for counter separator
        is_duplicate (bool): If True, check if file is a duplicate
    
    Returns:
        tuple: (Path to target directory, unique filename, is_exact_duplicate)
    """
    logger.debug(f"Generating unique filename:")
    logger.debug(f"  Base path: {base_path}")
    logger.debug(f"  Proposed filename: {proposed_filename}")
    logger.debug(f"  Source path: {source_path}")
    
    separator = '-' if use_dashes else '_'
    name, ext = os.path.splitext(proposed_filename)
    target_dir = Path(base_path)
    
    # Remove any existing counter pattern from the name (e.g., '_001', '_002')
    # First try to find the last occurrence of _XXX or -XXX
    match = re.search(r'([_-]\d{3})(?:[_-]|$)', name)
    if match:
        counter_part = match.group(1)
        base_name = name[:name.rfind(counter_part)]
        logger.debug(f"  Found counter pattern '{counter_part}' in filename")
    else:
        base_name = name
    logger.debug(f"  Base name after removing counter: {base_name}")
    
    # If we're checking for duplicates, first scan the directory for any existing versions
    if is_duplicate and source_path:
        # Check the base filename without counter
        base_pattern = f"{base_name}{ext}"
        base_file = target_dir / base_pattern
        logger.debug(f"  Checking base file: {base_file}")
        if base_file.exists():
            logger.debug("  Base file exists, checking if duplicate")
            if is_duplicate_file(source_path, base_file):
                logger.info(f"Found exact duplicate: '{source_path}' matches existing file '{base_file}'")
                return target_dir, base_pattern, True
        
        # Check all numbered versions
        pattern = f"{base_name}[_-][0-9][0-9][0-9]{ext}"
        logger.debug(f"  Checking numbered versions with pattern: {pattern}")
        for existing_file in sorted(target_dir.glob(pattern)):
            logger.debug(f"  Checking numbered file: {existing_file}")
            if is_duplicate_file(source_path, existing_file):
                logger.info(f"Found exact duplicate: '{source_path}' matches existing file '{existing_file}'")
                return target_dir, existing_file.name, True
    
    # If no duplicates found, find a unique filename
    counter = 0
    while True:
        if counter == 0:
            new_name = f"{base_name}{ext}"
        else:
            new_name = f"{base_name}{separator}{counter:03d}{ext}"
            
        full_path = target_dir / new_name
        logger.debug(f"  Trying filename: {full_path}")
        if not full_path.exists():
            logger.debug(f"  Found unique filename: {new_name}")
            return target_dir, new_name, False
            
        counter += 1

def organize_by_date(base_path: Path, date_time: datetime) -> Path:
    """
    Create a date-based folder structure and return the full path.
    Uses format: YYYY/YYYY-MM/YYYY-MM-DD
    
    Args:
        base_path: Base directory path
        date_time: DateTime object to use for folder structure
        
    Returns:
        Path object with the complete date-based directory structure
    """
    year_str = str(date_time.year)
    month_str = f"{date_time.year}-{date_time.month:02d}"
    day_str = f"{date_time.year}-{date_time.month:02d}-{date_time.day:02d}"
    
    year_dir = base_path / year_str
    month_dir = year_dir / month_str
    day_dir = month_dir / day_str
    
    # Create all directories
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir

def extract_timestamp_from_filename(filename: str) -> Optional[tuple[datetime, str]]:
    """
    Extract timestamp from filename and return the timestamp and remaining filename parts.
    Removes any timestamp patterns from the remaining filename.
    
    Args:
        filename: Original filename to process
        
    Returns:
        Tuple of (datetime object, remaining filename) or None if no timestamp found
    """
    # Get the name without extension
    name = Path(filename).stem
    
    # Try to extract date using existing function first
    date_time = extract_date_from_filename(name)
    if date_time:
        # Find and remove all possible timestamp patterns
        patterns = [
            r'\d{8}[-_]\d{6}',            # YYYYMMDD-HHMMSS or YYYYMMDD_HHMMSS
            r'\d{4}-\d{2}-\d{2}[-_]\d{2}[-_]\d{2}[-_]\d{2}',  # YYYY-MM-DD-HH-MM-SS or with underscores
            r'\d{4}[-_]\d{2}[-_]\d{2}[-_]\d{2}[-_]\d{2}[-_]\d{2}',  # YYYY_MM_DD_HH_MM_SS or with dashes
            r'\d{2}-\d{2}-\d{4}[-_]\d{6}',              # DD-MM-YYYY_HHMMSS
            r'\d{14}',                                    # YYYYMMDDHHMMSS
            r'\d{4}-\d{2}-\d{2}',                        # YYYY-MM-DD
            r'\d{2}-\d{2}-\d{4}',                        # DD-MM-YYYY
            r'\d{8}',                                     # YYYYMMDD
            r'\d{6}[-_]\d{6}'                            # DDMMYY-HHMMSS
        ]
        
        remaining = name
        # Remove all timestamp patterns from the remaining filename
        for pattern in patterns:
            remaining = re.sub(pattern, '', remaining)
        
        # Clean up any leftover separators at start/end and multiple separators
        remaining = re.sub(r'[-_]+', '-', remaining.strip('_- '))
        
        if remaining:
            return date_time, remaining
        else:
            return date_time, "file"  # Default name if nothing remains
    
    return None

def main():
    """
    Main function to process all photos in the input directory and its subdirectories.
    """
    # Ensure all required directories exist
    ensure_directories_exist()
    
    # Process all files in input directory recursively
    input_path = Path(INPUT_DIR)
    if not input_path.exists():
        logger.error(f"Input directory does not exist: {INPUT_DIR}")
        return
    
    total_files = 0
    processed_files = 0
    
    # Collect all directories first
    all_dirs = set()
    for root, dirs, files in os.walk(input_path, topdown=False):
        all_dirs.add(Path(root))
        
        # Process files if any
        for filename in files:
            total_files += 1
            file_path = Path(root) / filename
            
            # Skip hidden files
            if filename.startswith('.') or filename.startswith('~$'):
                logger.debug(f"Skipping hidden/system file: {file_path}")
                continue
            
            # Get the file extension
            file_ext = os.path.splitext(filename)[1].lower()
            
            # Check if it's a supported file type
            if file_ext in SUPPORTED_EXTENSIONS:
                logger.info(f"Processing file: {file_path}")
                if process_photo(file_path):
                    processed_files += 1
            else:
                logger.debug(f"Skipping unsupported file type: {file_path}")
    
    # Clean up all directories bottom-up (from deepest to shallowest)
    for dir_path in sorted(all_dirs, key=lambda x: len(str(x)), reverse=True):
        cleanup_directory(dir_path)
    
    if total_files > 0:
        logger.info(f"Processed {processed_files} of {total_files} files")

if __name__ == "__main__":
    main()
