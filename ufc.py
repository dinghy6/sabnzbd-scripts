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

import sys
import re
from shutil import move # shutil turned out to be more reliable than pathlib for moving
from pathlib import Path

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


def exit_log(message: str = "", exit_code: int = 1) -> None:

    """
    Logs a message and exits the program with the specified exit code.

    Prints the provided message followed by newlines so
    that the 'more' button is available in sabnzbd.
    Terminates the program using sys.exit with the given exit code.

    :param message: The message to be logged before exiting.
    :type message: str
    :param exit_code: The exit code to be used when terminating the program.
    :type exit_code: int
    :return: None
    """

    print(f"Error: {message}" if exit_code else message)
    print("\n\n\n")
    sys.exit(exit_code)


def get_resolution(file_path: Path, include_scan_mode: bool = False) -> int | str | None:

    """
    Extracts the resolution from a video file name. Not trying to be perfect here.

    if include_scan_mode is false, returns an int where higher = better resolution for comparison.
    if include_scan_mode is true, returns a string of the resolution and scan mode.
    If no resolution is found, returns None.

    :param file_path: The path to the video file.
    :type file_path: Path
    :param include_scan_mode: Whether to include the scan mode in the resolution.
    :type include_scan_mode: bool
    :return: The extracted resolution or None if no resolution is found.
    :rtype: int | str | None
    """

    file_name = re.sub(r'4k|uhd', '2160p', file_path.name, re.IGNORECASE)
    match = re.search(r'(?P<res>\d{3,4})[pi]', file_name, re.IGNORECASE)

    if not match:
        return None

    if include_scan_mode:
        return match.group(0)
    
    return int(match.group('res'))


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


def extract_info(file_name: str) -> tuple[str, str, str]:

    """
    Extract UFC event number, fighter names, and edition from a filename.
    
    Uses a regular expression to extract the information from the filename. 
    If the extraction is successful, returns a tuple of (event_number, fighter_names, edition).
    Event number is in the format "UFC 300" or "UFC Fight Night 248" or "UFC on ABC 7".
    If the event number is not found, prints an error message and exits.

    :param file_name: The file name to extract information from
    :type file_name: str
    :return: A tuple of (event_number, fighter_names, edition)
    :rtype: tuple[str, str, str]
    """

    # unify separators to spaces
    file_name = re.sub(r'[\.\s_]', ' ', file_name)

    # Doozy of a regex. Using global search because sometimes they appear out of order
    pattern = (
        # Event number
        r'ufc (?P<ppv>\d{1,4})'  # e.g. ufc 300
        r'|ufc fight night (?P<fnight>\d{1,4})'  # e.g. ufc fight night 248
        r'|ufc on (?P<ufc_on>\w+ \d{1,4})'  # e.g. ufc on abc 7
        #
        # Fighter names (x vs y)
        # old name pattern: r'|(?P<names>\w+\.?vs\.?\w+)'
        # > had issues with names that had a separator inside the name
        # new name pattern after selling my soul:
        r'|(?P<names>((?<= )[a-z-]+ ?)+vs( ?(?!ppv|main|prelim|early|web|[0-9])[a-z-]+?(?= ))+(?: (?![0-9]{2,})[0-9])?)'
        #                                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        # NOTE: if an additional word is added to the end of the name (e.g. "Yan vs Figueiredo ppv"),
        #       it needs to be added in the first negative lookahead as indicated above
        #
        # Edition (not including ppv because it is often ommitted anyway)
        r'|(?P<edition>early prelims|prelims|preliminary)'
    )

    matches = re.finditer(pattern, file_name, re.I)

    event_number, fighter_names, edition = '', '', ''

    for match in matches:

        if match.group('ppv'):
            event_number = f"UFC {match.group('ppv')}"
        elif match.group('fnight'):
            event_number = f"UFC Fight Night {match.group('fnight')}"
        elif match.group('ufc_on'):
            event_number = f"UFC on {match.group('ufc_on')}"

        if match.group('names'):
            fighter_names = f"{match.group('names')}"
            fighter_names = ' '.join(w.title() for w in fighter_names.split())
            fighter_names = fighter_names.replace(' Vs ', ' vs ')

        if match.group('edition'):
            edition = match.group('edition')
            edition = ' '.join(w.capitalize() for w in edition.split())
            # Correct weird edition names
            edition = EDITION_MAP.get(edition, edition)

    if not event_number:
        if STRICT_MATCHING:
            # error exit
            exit_log(f"Unable to extract UFC event number from {file_name}", 1)
        else:
            # silent exit
            exit_log(exit_code=0)

    return event_number, fighter_names, f"{{edition-{edition or 'Main Event'}}}"


def construct_path(file_path: Path) -> Path:

    """
    Constructs a new file path for a UFC video file based on extracted information.

    Folder format:
    {event_number} {fighter_names} {edition}

    File format:
    {event_number} {fighter_names} {edition} {resolution}.{suffix}

    The fighter names and resolution may be ommitted if not found in the file name.

    :param file_path: The full path to the original video file.
    :type file_path: Path
    :return: The constructed file path including the new folder and file name.
    :rtype: Path
    """

    parts = [*extract_info(file_path.stem)]

    # e.g. UFC Fight Night 248 Yan vs Figueiredo {edition-Main Event}
    folder_name = " ".join(parts)

    parts.append(get_resolution(file_path, include_scan_mode=True))

    # e.g. UFC Fight Night 248 Yan vs Figueiredo {edition-Main Event} 1080p.mkv
    file_name = " ".join(parts) + file_path.suffix

    return Path(DESTINATION_FOLDER) / folder_name / file_name


def rename_and_move(file_path: Path) -> tuple[str, int]:

    """
    Renames and moves a UFC video file to a new directory based on extracted information.

    Moves the file to the new location under the DESTINATION_FOLDER 
    directory.

    If the extraction is unsuccessful, an error message is printed and the script exits.

    :param file_path: The full path to the downloaded video file.
    :type file_path: Path
    :return: A tuple containing a boolean indicating success and an error message.
    :rtype: tuple[str, int]
    """

    new_path = construct_path(file_path)

    if new_path.exists():
        # If the new file already exists, print an error and exit
        return f"File {new_path.name} already exists in {new_path.parent}", 1

    # Move the file to the new folder
    try:
        if not new_path.parent.exists():
            # If the destination folder does not exist, create it and move the file
            new_path.parent.mkdir(parents=True)
            move(file_path, new_path)
            return f"Moved {file_path} to {new_path}", 0

        # Check if the new folder already contains a video file
        existing = find_largest_video_file(new_path.parent)

        if not existing:
            # If no video files exist in the destination folder, move the file
            move(file_path, new_path)
            return f"Moved {file_path} to {new_path}", 0

        # If a video file already exists in the destination folder, check its resolution
        # if there is no resolution in either, the new file is preferred
        new_res = get_resolution(file_path) or 99999
        old_res = get_resolution(existing) or 0

        if new_res == old_res and not REPLACE_SAME_RES:

            # If the resolutions are the same, ignore
            return f"File {existing.name} already exists in {new_path.parent} with the same resolution.", 0

        elif new_res < old_res:

            # If the existing file has a higher resolution, error
            return f"File {existing.name} already exists in {new_path.parent} with a higher resolution.", 1

        else:
            # If the downloaded file has a higher resolution, replace the existing file
            try:
                existing.unlink()
                print(f"Removed lower resolution file {existing.name}")
            except OSError as e:
                print(f"Error deleting file: {e}")

            move(file_path, new_path)
            return f"Moved {file_path} to {new_path}", 0

    except (FileNotFoundError, OSError, PermissionError, TypeError) as e:
        return f"Could not move file: {e}", 1


def main() -> None:

    """
    Main function. For integration with other downloaders, modify the sys.argv calls.

    If it is called by SABnzbd, 9 arguments should be passed in by SABnzbd.

    sys.argv[1] is the full path to the folder containing the video files to be 
    processed.

    sys.argv[5] is the category of the download. If it matches UFC_CATEGORY, 
    the script will fail if it cannot find the event number in the filename.

    The script will filter the files in the directory to find the largest video file, 
    and then attempt to rename and move it to the specified destination folder.

    If the video file is successfully moved, the script will exit with 0. 
    If there is an error, the script will exit with 1.

    :return: None
    """

    # Print newlines so the 'more' button is available in sabnzbd
    print("\n\n\n")

    if len(sys.argv) >= 9:
        try:
            # make sure the path is valid
            directory = Path(sys.argv[1])
        except (TypeError, ValueError) as e:
            return exit_log(f"Invalid directory path: {e}", 1)

        if sys.argv[5] == UFC_CATEGORY:
            globals()['STRICT_MATCHING'] = True
    else:
        return exit_log("Not enough arguments.", 1)

    # Filter video files
    video_file = find_largest_video_file(directory)

    if not video_file:
        return exit_log("No video files found.", 1)

    exit_log(*rename_and_move(video_file))


if __name__ == "__main__":
    main()

sys.exit(0)
