#!/usr/bin/env python3

import os
import hashlib
import argparse
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set
import logging
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class DuplicateFinder:
    def __init__(self, directory: str):
        self.directory = Path(directory)
        self.hash_map: Dict[str, List[Path]] = defaultdict(list)
        # Regular expression for matching numbered suffixes like _001, _1, etc.
        self.numbered_suffix_pattern = re.compile(r'_\d+$')
        
    def calculate_file_hash(self, filepath: Path) -> str:
        """Calculate SHA-256 hash of a file."""
        hash_sha256 = hashlib.sha256()
        
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        except Exception as e:
            logging.error(f"Error calculating hash for {filepath}: {e}")
            return ""

    def rename_jpeg_to_jpg(self, filepath: Path) -> Path:
        """Rename .jpeg files to .jpg extension."""
        if filepath.suffix.lower() in ['.jpeg']:
            new_filepath = filepath.with_suffix('.jpg')
            try:
                filepath.rename(new_filepath)
                logging.info(f"Renamed {filepath} to {new_filepath}")
                return new_filepath
            except Exception as e:
                logging.error(f"Error renaming {filepath}: {e}")
                return filepath
        return filepath

    def find_duplicates(self) -> Dict[str, List[Path]]:
        """Scan directory and find duplicate files based on content."""
        logging.info(f"Scanning directory: {self.directory}")
        
        file_count = 0
        for filepath in self.directory.rglob("*"):
            if filepath.is_file():
                logging.info(f"Processing: {filepath}")
                # Rename jpeg to jpg if necessary
                filepath = self.rename_jpeg_to_jpg(filepath)
                file_count += 1
                file_hash = self.calculate_file_hash(filepath)
                if file_hash:
                    self.hash_map[file_hash].append(filepath)
        
        # Filter out files without duplicates
        duplicates = {k: v for k, v in self.hash_map.items() if len(v) > 1}
        
        logging.info(f"Processed {file_count} files total")
        if duplicates:
            total_duplicates = sum(len(files) for files in duplicates.values())
            logging.info(f"Found {len(duplicates)} groups of duplicates with {total_duplicates} total files")
        else:
            logging.info("No duplicate files found")
            
        return duplicates

    def has_numbered_suffix(self, filename: str) -> bool:
        """Check if the filename ends with a numbered suffix like _001."""
        return bool(self.numbered_suffix_pattern.search(filename.rsplit('.', 1)[0]))
    
    def get_filename_score(self, filepath: Path) -> tuple:
        """
        Calculate a score for filename prioritization.
        Returns a tuple of (is_not_numbered, filename_length) for sorting.
        Files without numbered suffixes get priority (1), files with numbered suffixes get (0).
        """
        filename = filepath.stem  # Get filename without extension
        is_not_numbered = 0 if self.has_numbered_suffix(filename) else 1
        return (is_not_numbered, len(filepath.name))

    def remove_duplicates(self, duplicates: Dict[str, List[Path]], keep_newest: bool = True, keep_longest_name: bool = False) -> None:
        """Remove duplicate files, keeping either the newest version or the one with the longest filename."""
        for hash_value, file_list in duplicates.items():
            if keep_longest_name:
                # Sort files by our custom scoring function
                # This will first prioritize files without numbered suffixes,
                # then by filename length within each group
                sorted_files = sorted(file_list, key=self.get_filename_score, reverse=True)
            else:
                # Sort files by modification time
                sorted_files = sorted(file_list, key=lambda x: x.stat().st_mtime, reverse=keep_newest)
            
            # Keep the first file (longest name or newest/oldest depending on settings)
            keep_file = sorted_files[0]
            files_to_remove = sorted_files[1:]
            
            logging.info(f"Keeping: {keep_file}")
            for file_to_remove in files_to_remove:
                try:
                    file_to_remove.unlink()
                    logging.info(f"Removed duplicate: {file_to_remove}")
                except Exception as e:
                    logging.error(f"Error removing {file_to_remove}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Find and manage duplicate files in a directory")
    parser.add_argument("directory", help="Directory to scan for duplicates")
    parser.add_argument("--remove", action="store_true", help="Remove duplicate files")
    parser.add_argument("--keep-oldest", action="store_true", help="Keep oldest version when removing duplicates")
    parser.add_argument("--keep-longest-name", action="store_true", 
                       help="Keep the file with the longest filename (contains more metadata)")
    parser.add_argument("--force", action="store_true", 
                       help="Don't ask for confirmation before removing files")
    
    args = parser.parse_args()
    
    finder = DuplicateFinder(args.directory)
    duplicates = finder.find_duplicates()
    
    if not duplicates:
        logging.info("No duplicate files found.")
        return
    
    # Print duplicate files
    for hash_value, file_list in duplicates.items():
        print(f"\nDuplicate files (hash: {hash_value}):")
        for file_path in file_list:
            numbered = "Yes" if finder.has_numbered_suffix(file_path.name) else "No"
            print(f"  - {file_path}")
            print(f"    (Name length: {len(file_path.name)}, Has numbered suffix: {numbered}, Modified: {file_path.stat().st_mtime})")
    
    if args.remove:
        total_duplicates = sum(len(files) - 1 for files in duplicates.values())
        if not args.force:
            confirm = input(f"\nAre you sure you want to remove {total_duplicates} duplicate files? (yes/no): ")
            if confirm.lower() != "yes":
                logging.info("Duplicate removal cancelled.")
                return
        
        finder.remove_duplicates(duplicates, 
                              keep_newest=not args.keep_oldest,
                              keep_longest_name=args.keep_longest_name)
        logging.info("Duplicate removal completed.")

if __name__ == "__main__":
    main()
