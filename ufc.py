"""

This script is used in SABnzbd's post-processing to move and rename UFC files.

The script will attempt to extract the UFC event number (event name), 
fighter names (title), and edition from the filename.

Plex uses editions to specify different versions of movies.
We can use this to differentiate between different versions of UFC files.

The editions used in output filenames are: Early Prelims, Prelims, and Main Event.

If the extraction is successful, the script will create a new folder in 
DESTINATION_FOLDER with the event number and edition name. It will then move the 
file to this new folder and rename it to include the event number, fighter names,
and edition.

If the extraction is unsuccessful or any other errors occur, the script will 
print an error message and exit with a non-zero exit code.

"""

import os
import sys
import re
import argparse
import shutil
from pathlib import Path
from enum import Enum


class Bracket(Enum):
    SQUARE = 'square'
    CURLY = 'curly'
    ROUND = 'round'


DESTINATION_FOLDER = r'/mnt/media/Sport/'

# if true, will remove existing files with the same resolution in the name
REPLACE_SAME_RES = True

# Dictionary to correct strange edition names
EDITION_MAP = {
    'Preliminary': 'Prelims',
}

# if false, will not error out if the event number can't be found.
# Instead, it is assumed the file is not meant to be a ufc file.
# This is for running on the movie category as well as TV > Sport
# because ufc files are often miscategorized.
# NOTE: If the category name is UFC_CATEGORY, STRICT_MATCHING will be set to True.
STRICT_MATCHING = False

UFC_CATEGORY = 'ufc'

# Formatting configuration. The keys must match the keys in extract_info().
# define the order of the parts (value here will be the index)
FORMAT_ORDER = {
    'event_number': 0,
    'fighter_names': 1,
    'edition': 2,
    'resolution': 3
}

# define which parts need brackets. Editions need curly brackets to be detected.
FORMAT_TOKENS = {
    'edition': Bracket.CURLY,
    'resolution': Bracket.SQUARE
}

# define which parts are used in the folder name. Order used is the same as FORMAT_ORDER.
# add 'edition' if you want each edition to have its own folder
FORMAT_FOLDER = {'event_number', 'fighter_names'}


def exit_log(message: str = "", exit_code: int = 1) -> None:
    """
    Logs a message and exits the program with the specified exit code.

    Prints the provided message then terminates the program using sys.exit with the given exit code.

    :param message: The message to be logged before exiting.
    :type message: str
    :param exit_code: The exit code to be used when terminating the program.
    :type exit_code: int
    :return: None
    """

    print(f"Error: {message}" if exit_code else message)
    sys.exit(exit_code)


def check_path(path: str) -> Path:
    """
    Checks if the given path exists and is a directory.

    If the path exists and is a directory, returns the Path object.
    If the path does not exist or is not a directory, raises a NotADirectoryError.

    :param path: The path to check.
    :type path: str
    :return: The Path object of the given directory.
    :rtype: Path
    :raises NotADirectoryError: If the path does not exist or is not a directory.
    """

    try:
        directory = Path(path)
        if not directory.exists() or not directory.is_dir():
            raise NotADirectoryError(
                f"Directory path '{directory}' does not exist or is not a directory")
    except (TypeError, ValueError) as e:
        raise NotADirectoryError(str(e)) from e

    return directory


def get_resolution(file_name: str, include_scan_mode: bool = False) -> int | str | None:
    """
    Extracts the resolution from a video file name. Not trying to be perfect here.

    if include_scan_mode is false, returns an int where higher = better resolution for comparison.
    if include_scan_mode is true, returns a string of the resolution and scan mode.
    If no resolution is found, returns None.

    :param file_name: The file name
    :type file_name: str
    :param include_scan_mode: Whether to include the scan mode in the resolution.
    :type include_scan_mode: bool
    :return: The extracted resolution or None if no resolution is found.
    :rtype: int | str | None
    """

    file_name = re.sub(r'4k|uhd', '2160p', file_name, re.IGNORECASE)
    match = re.search(r'(?P<res>\d{3,4})[pi]', file_name, re.IGNORECASE)

    if not match:
        return None

    if include_scan_mode:
        return match.group(0)

    return int(match.group('res'))


def get_editions(path: Path, event_number: str) -> dict[str, dict[str, str]]:
    """
    Scans the given directory and extracts editions from the file names.

    Iterates over each file in the specified directory, extracts the edition
    information from the file name, and returns a dictionary mapping each
    edition to its corresponding file path. If a file does not contain
    edition information, it is not included in the result.

    :param path: The directory path to scan for files.
    :type path: Path
    :return: A dictionary where keys are edition names and values are file paths.
    :rtype: dict[str, dict[str, str]]
    """

    editions_in_folder = {}
    for file in path.iterdir():
        if file.is_file():
            info = extract_info(file.stem, strict=False)
            edition = extract_info(file.stem, strict=False).get('edition')
            if edition and info.get('event_number') == event_number:
                editions_in_folder[edition] = {
                    'path': str(file),
                    'event_number': info.get('event_number') or '',
                    'fighter_names': info.get('fighter_names') or '',
                    'resolution': info.get('resolution') or ''
                }
    return editions_in_folder


def find_largest_video_file(video_path: Path) -> Path | None:
    """
    Finds the largest video file in the given path.

    Valid video file extensions are .mp4, .mkv, .avi and .mov.
    If video files are found, it returns the largest one based on file size,
    because sometimes a sample video or thumbnail is included.
    If no video files are found, returns None.

    :param video_path: The path to search for video files.
    :type video_path: Path
    :return: The largest video file path or None if no video files are found.
    :rtype: Path | None
    """

    video_files = [
        f for f in video_path.iterdir()
        if f.is_file() and f.suffix in ['.mp4', '.mkv', '.avi', '.mov']
    ]

    if not video_files:
        return None

    return max(video_files, key=lambda f: f.stat().st_size)


def find_names(event_number: str) -> str:
    """
    Attempts to find fighter names of a given ufc event from an existing folder.

    Searches for a folder in DESTINATION_FOLDER that starts with the event number.
    If a folder is found, it will attempt to extract the fighter names from the folder name.

    :param event_number: The UFC event number.
    :type event_number: str
    :return: The fighter names.
    :rtype: str
    """

    for path in Path(DESTINATION_FOLDER).glob(f"{event_number}*"):
        if path.is_dir():
            info = extract_info(path.name, False)
            if info['fighter_names']:
                return info['fighter_names']

    return ''


def extract_info(file_name: str, strict: bool = True) -> dict[str, str]:
    """
    Extract UFC event number, fighter names, and edition from a filename.

    Uses regex to extract the information from the filename. 
    First tries to find the UFC event number. If not found, the script exits.
    How it exits is determined by the STRICT_MATCHING variable.
    If the extraction is successful, returns a dictionary of info found.

    :param file_name: The file name to extract information from
    :type file_name: str
    :param strict: Whether to try hard or not
    :type strict: bool
    :return: A dictionary of extracted information. Keys are the same as the FORMAT_ORDER keys
    :rtype: dict[str, str]
    """

    # Unify separators to spaces
    file_name = re.sub(r'[\.\s_]', ' ', file_name)

    event_number, fighter_names, edition = '', '', ''

    # Event number
    # there are also 'UFC Live' events which will not be caught, but they usually
    # don't have a number anyway
    pattern = r'ufc (?P<ppv>\d{1,4})|ufc fight night (?P<fnight>\d{1,4})|ufc on (?P<ufc_on>\w+ \d{1,4})'
    match = re.search(pattern, file_name, re.IGNORECASE)

    if not match and strict:
        if STRICT_MATCHING:
            # error exit
            exit_log(f"Unable to extract UFC event number from {file_name}", 1)
        else:
            # silent exit
            exit_log(exit_code=0)
        sys.exit()  # for clarity
    elif match:
        if match.group('ppv'):
            event_number = f"UFC {match.group('ppv')}"
        elif match.group('fnight'):
            event_number = f"UFC Fight Night {match.group('fnight')}"
        elif match.group('ufc_on'):
            event_number = f"UFC on {match.group('ufc_on').upper()}"

    # file_name = file_name[:match.start()] + file_name[match.end():]

    # Find the rest. Using global search because sometimes they appear out of order
    pattern = (
        # Fighter names (x vs y)
        r'(?P<names>((?:(?<= )|(?<=^))(?!ppv|main|event|prelim|preliminary)[a-z-]+ )+vs( (?!ppv|main|prelim|early|web)[a-z-]+(?= |$))+(?: (?![0-9]{2,})[0-9])?)'
        # NOTE: If additional words end up in the name, add them to the regex

        # Edition (not including ppv because it is often ommitted)
        r'|(?P<edition>early prelims|prelims|preliminary)'
    )

    matches = re.finditer(pattern, file_name, re.IGNORECASE)

    for match in matches:
        if match.group('names'):
            fighter_names = f"{match.group('names')}"
            fighter_names = ' '.join(w.title() for w in fighter_names.split())
            fighter_names = fighter_names.replace(' Vs ', ' vs ')

        if match.group('edition'):
            edition = match.group('edition')
            edition = ' '.join(w.capitalize() for w in edition.split())
            # Correct weird edition names
            edition = EDITION_MAP.get(edition, edition)

    if not fighter_names and strict:
        fighter_names = find_names(event_number)

    return {
        'event_number': event_number,
        'fighter_names': fighter_names,
        'edition': f"edition-{edition or 'Main Event'}",
        'resolution': str(get_resolution(file_name, True) or '')
    }


def construct_path(file_path: Path) -> tuple[Path, dict[str, str]]:
    """
    Constructs a new file path for a UFC video file based on extracted information.

    The formatting is defined in the FORMAT_X variables.
    The fighter names and resolution may be ommitted if not found in the file name.

    :param file_path: The full path to the original video file.
    :type file_path: Path
    :return: A tuple containing the new file path and a dictionary of extracted information.
    :rtype: tuple[Path, dict[str, str]]
    """

    parts = [''] * len(FORMAT_ORDER)
    folder_parts = [''] * len(FORMAT_ORDER)

    info = extract_info(file_path.stem)
    for key, value in info.items():
        if not value:
            continue

        if key not in FORMAT_ORDER:
            exit_log(f"FORMAT_ORDER does not contain {key}", 1)
            sys.exit()

        index = FORMAT_ORDER[key]
        token = FORMAT_TOKENS.get(key)

        if token == Bracket.CURLY:
            value = '{' + value + '}'
        elif token == Bracket.SQUARE:
            value = '[' + value + ']'

        parts[index] = value

        if key in FORMAT_FOLDER:
            folder_parts[index] = value

    # e.g. UFC Fight Night 248 Yan vs Figueiredo
    folder_name = " ".join(filter(None, folder_parts))

    # e.g. UFC Fight Night 248 Yan vs Figueiredo {edition-Main Event} [1080p].mkv
    file_name = " ".join(filter(None, parts)) + file_path.suffix

    return Path(DESTINATION_FOLDER) / folder_name / file_name, info


def move_file(file_path: Path, new_path: Path, dry_run: bool = False) -> tuple[str, int]:
    """
    Moves a video file from its original location to a new location.

    :param file_path: The full path to the original video file.
    :type file_path: Path
    :param new_path: The full path to the new video file.
    :type new_path: Path
    :param dry_run: Whether to perform a dry run (default: False).
    :type dry_run: bool
    :return: A tuple containing a boolean indicating success and an error message.
    :rtype: tuple[str, int]
    """

    if dry_run:
        return f"Moved {file_path} to {new_path}", 0

    if not new_path.parent.exists():
        new_path.parent.mkdir(parents=True)

    if not new_path.iterdir():
        shutil.move(file_path, new_path)
    else:
        shutil.copy2(file_path, new_path)

    file_path.unlink()

    return f"Moved {file_path} to {new_path}", 0


def rename_and_move(file_path: Path, dry_run: bool = False, bulk_rename: bool = False) -> tuple[str, int]:
    """
    Renames and moves a UFC video file to a new directory based on extracted information.

    Moves the file to the new location under the DESTINATION_FOLDER 
    directory.

    If the extraction is unsuccessful, an error message is printed and the script exits.

    :param file_path: The full path to the downloaded video file.
    :type file_path: Path
    :param dry_run: Whether to perform a dry run (default: False).
    :type dry_run: bool
    :return: A tuple containing a boolean indicating success and an error message.
    :rtype: tuple[str, int]
    """

    new_path, info = construct_path(file_path)

    if new_path.exists():
        # If the new file already exists, print an error and exit
        return f"File {new_path.name} already exists in {new_path.parent}", 1

    # Move the file to the new folder
    try:
        if not new_path.parent.exists() or bulk_rename:
            return move_file(file_path, new_path, dry_run)

        # find existing video file with same edition
        existing = get_editions(new_path.parent, info['event_number']).get(
            info['event_number'])

        if not existing or not existing.get(info['edition']):
            return move_file(file_path, new_path, dry_run)

        # edition already exists in folder

        # if there is no resolution in either, the new file is preferred
        new_res = int(info['resolution'][:-1] or 99999)
        old_res = int(existing['resolution'][:-1] or 0)

        if new_res == old_res and not REPLACE_SAME_RES:

            # If the resolutions are the same, ignore
            return f"File {existing.name} already exists in {new_path.parent} with the same resolution.", 0

        elif new_res < old_res:

            # If the existing file has a higher resolution, error
            return f"File {existing.name} already exists in {new_path.parent} with a higher resolution.", 1

        else:
            # If the downloaded file has a higher resolution, replace the existing file
            if existing[info['edition']]['path'] != new_path:
                if dry_run:
                    print(f"Removed lower resolution file {existing.name}")

                try:
                    existing.unlink()
                    print(f"Removed lower resolution file {existing.name}")
                except OSError as e:
                    print(f"Error deleting file: {e}")

            return move_file(file_path, new_path, dry_run)

    except (FileNotFoundError, OSError, PermissionError, TypeError) as e:
        return f"Could not move file: {e}", 1


def parse_args():
    """
    Parses command line arguments. Only called if sys.argv[1] is not a directory.

    Mostly made this for re-organization of existing files. Can use arguments
    to run manually. Quick run: python ufc.py -d /path/to/downloaded/folder

    :return: The folder containing the video files.
    :rtype: any
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--dir', default=DESTINATION_FOLDER,
                        help="The directory containing the video files to be processed")
    parser.add_argument(
        '-c', '--category', help="The category of the download. If it matches UFC_CATEGORY, STRICT_MATCHING will be set to True")
    parser.add_argument(
        '-D', '--dest', help="The destination folder for the renamed files")
    parser.add_argument('-r', '--replace-same-res', action='store_true',
                        help="Replace existing files with the same resolution in the name")
    parser.add_argument('-s', '--strict-matching', action='store_true',
                        help="Fail if the event number cannot be found in the file name")
    parser.add_argument('--rename-all', action='store_true',
                        help="Rename all UFC folders and files in the directory. Use with caution.")
    parser.add_argument('--remove-renamed', action='store_true',
                        help="Remove empty folders after renaming.")
    parser.add_argument('--force', action='store_true',
                        help="Force removal of renamed folders. Warning: This deletes all files left in the folder.")
    parser.add_argument('--dry-run', action='store_true',
                        help="Print out the new filenames without actually moving the files.")
    args = parser.parse_args()

    if args.dest:
        globals()['DESTINATION_FOLDER'] = args.dest

    if args.replace_same_res:
        globals()['REPLACE_SAME_RES'] = True

    if args.strict_matching or args.category == UFC_CATEGORY:
        globals()['STRICT_MATCHING'] = True

    directory = args.dir

    if not args.rename_all:
        return directory

    try:
        directory = check_path(directory)
    except NotADirectoryError as e:
        exit_log(str(e), 1)
        sys.exit(1)

    # rename all UFC folders and files in given directory
    dirs = [d for d in directory.iterdir() if d.is_dir()]

    for folder in dirs:

        if folder.is_dir():
            renamed = True  # so that we don't delete if there was an error

            for file in folder.iterdir():
                if file.is_file() and file.suffix in ['.mp4', '.mkv', '.avi', '.mov']:

                    message, exit_code = rename_and_move(
                        file, args.dry_run, True)

                    print("Error: " + message if exit_code else message)

                    if exit_code:
                        renamed = False

            if renamed and args.remove_renamed and (len(list(folder.iterdir())) == 0 or args.force):
                if args.dry_run:
                    print(f"Removing empty folder {folder}")
                elif args.force:
                    shutil.rmtree(folder)  # scorched earth
                else:
                    folder.rmdir()

    exit_log("Done.", 0)
    sys.exit(0)


def main() -> None:
    """
    Main function.

    If it is called by SABnzbd, the environment variables 'SAB_COMPLETE_DIR'
    and 'SAB_CAT' will be set.

    The script will filter the files in the directory to find the largest video file, 
    and then attempt to rename and move it to the specified destination folder.

    If the video file is successfully moved, the script will exit with 0. 
    If there is an error, the script will exit with 1.

    :return: None
    """

    # Print newlines so the 'more' button is available in sabnzbd
    print("\n\n\n")

    directory, category = None, None

    if len(sys.argv) == 1:
        return exit_log("Not enough arguments.", 1)

    if len(sys.argv) == 2:
        # only a job path is provided
        directory = sys.argv[1]

    elif os.getenv('SAB_VERSION'):
        # running from SABnzbd
        # Print newlines so the 'more' button is available in sabnzbd
        print("\n\n\n")
        directory = os.getenv('SAB_COMPLETE_DIR')
        category = os.getenv('SAB_CAT')

        if not directory or not category:
            return exit_log("SAB_COMPLETE_DIR or SAB_CAT not set.", 1)

    else:
        # running manually
        directory = parse_args()

    try:
        directory = check_path(directory)
    except NotADirectoryError as e:
        return exit_log(f"Invalid job directory: {e}", 1)

    if category == UFC_CATEGORY:
        globals()['STRICT_MATCHING'] = True

    # Filter video files
    video_file = find_largest_video_file(directory)

    if not video_file:
        return exit_log("No video files found.", 1)

    exit_log(*rename_and_move(video_file))


main()

sys.exit(0)
