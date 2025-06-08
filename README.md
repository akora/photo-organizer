# Photo Organizer

A powerful Python script for organizing and managing your photo collection. This script automatically organizes photos based on their creation date, camera information, and file type, while handling duplicates and maintaining a clean directory structure.

## Features

- Organizes photos into a structured date-based hierarchy (YYYY/YYYY-MM/YYYY-MM-DD)
- Separates photos by type (JPG, RAW, other)
- Extracts and uses EXIF metadata (creation date, camera make/model, shutter count)
- Handles screenshots and non-camera images separately
- Detects and handles duplicate files
- Preserves file naming patterns and important metadata
- Cleans up empty directories and handles unprocessable files
- Supports various image formats:
  - JPEG (.jpg, .jpeg)
  - RAW formats (.arw, .cr2, .nef)
  - HEIC (iPhone photos)
  - Other formats (.gif, .png, .bmp, .tiff)
  - Vector graphics (.svg, .eps, .ai)
  - Icon files (.ico, .icns)

## Prerequisites

- Python 3.x
- exiftool (for reading image metadata)

### Installing exiftool

On macOS using Homebrew:

```bash
brew install exiftool
```

## Configuration

The script uses the following default directories (configured at the top of the script):

```python
INPUT_DIR = "./input"
OUTPUT_DIR = "./output"
UNPROCESSED_DIR = "./output/unprocessed"
```

Modify these paths in the script to match your desired directory structure.

## Installation

1. Clone this repository:

```bash
git clone https://github.com/yourusername/photo-organizer.git
cd photo-organizer
```

1. Create the required directories:

```bash
mkdir -p input output/unprocessed
```

## Usage

1. Place your photos in the configured input directory
2. Run the script:

```bash
python3 photo_organizer.py
```

The script will:

1. Process all photos in the input directory and its subdirectories
2. Organize files into the following structure:

   ```text
   OUTPUT_DIR/
   ├── jpg/
   │   └── YYYY/
   │       └── YYYY-MM/
   │           └── YYYY-MM-DD/
   │               └── YYYYMMDD-HHMMSS_[ShutterCount]_[CameraMake-Model].jpg
   ├── raw/
   │   └── [Same structure as jpg]
   ├── screenshots/
   ├── non_camera_images/
   │   ├── icons/
   │   ├── vector/
   │   └── graphics/
   └── unprocessed/
   ```

## File Naming Convention

Processed photos are renamed using the following format:

```text
YYYYMMDD-HHMMSS_[ShutterCount]_[CameraMake-Model].[ext]
```

Example:

```text
20231220-153000_12345_NikonD5100.jpg
```

## Handling Special Cases

- **Invalid Dates**: Files with unrealistic dates (e.g., 1970-01-01) will attempt to extract dates from filenames
- **Duplicates**: Exact duplicates are detected using size and content comparison
- **Unprocessable Files**: Files that can't be properly processed are moved to the unprocessed directory
- **Screenshots**: Automatically detected and moved to a dedicated screenshots folder
- **Non-camera Images**: Graphics, icons, and vector files are organized in separate directories

## Error Handling

The script includes comprehensive error handling and logging:

- Failed operations are logged with appropriate error messages
- Unprocessable files are moved to the unprocessed directory
- The script continues processing even if individual files fail

## Contributing

Feel free to submit issues and enhancement requests!
