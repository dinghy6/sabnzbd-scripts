"""
This script is used in SABnzbd's post-processing to move and rename UFC files.

The script will attempt to extract the UFC event number (event name),
fighter names (title), and edition from the filename. Plex uses editions
to specify different versions of movies. We can use this to differentiate
between different versions of UFC files.

The editions used in output filenames are: Early Prelims, Prelims, and Main Event.

If the extraction is successful, the script will create a new folder in
DESTINATION_FOLDER. It will then rename and move the file to the new folder.

The formatting of the folder name and filenames is defined in the script.

If the extraction is unsuccessful or any other errors occur, the script will
print an error message and exit with a non-zero exit code.
"""

import os
import sys
import re
import argparse
import shutil
from dataclasses import dataclass, fields
from pathlib import Path
from enum import Enum
from typing import NoReturn


class Bracket(Enum):
    SQUARE = "square"
    CURLY = "curly"
    ROUND = "round"


@dataclass
class VideoInfo:
    """Defines video information extracted from the file name."""

    event_number: str = ""
    fighter_names: str = ""
    edition: str = ""
    resolution: str = ""
    path: Path = Path("")


# =========================== GLOBALS CONFIGURATION ============================

# Full path to the destination folder
DESTINATION_FOLDER = Path(r"/mnt/media/Sport/")

# UFC-specific category to ensure jobs from this category are processed or failed
# Other categories will be ignored if processing fails, unless `STRICT_MATCHING` is True
UFC_CATEGORY = "ufc"

# If True, will remove existing files with the same edition and resolution in the name
# Set this to True to rename existing files during a bulk rename
REPLACE_SAME_RES = False

# If False, will not error out if the event number can't be found
# NOTE: If the category name is `UFC_CATEGORY`, `STRICT_MATCHING` will be set to True
STRICT_MATCHING = False

# If True, will not make any changes
DRY_RUN = False

# Valid video file extensions
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov"}

# TODO: Subfolder to put the prelims in
SUB_FOLDER = "Other"


# ========================== FORMATTING CONFIGURATION ==========================
# NOTE: The keys must match the attributes of VideoInfo (except `path`)

# Define the order of the parts (value here will be the index, order of dict is not important)
# If a part should not be used, set the value to None. `event_number` is required
FORMAT_ORDER = {"event_number": 0, "fighter_names": 1, "edition": 2, "resolution": 3}

# Define which parts need brackets. Editions need curly brackets to be detected
FORMAT_TOKENS = {"edition": Bracket.CURLY, "resolution": Bracket.SQUARE}

# Define which parts are used in the folder name. Order used is the same as FORMAT_ORDER
# Add 'edition' if you want each edition to have its own folder
FORMAT_FOLDER = {"event_number", "fighter_names"}

# ==============================================================================


def exit_log(message: str = "", exit_code: int = 1) -> NoReturn:
    """
    Logs a message and exits the program with the specified exit code.

    Prints the provided message then terminates the program using sys.exit with the given exit code.

    :param message: The message to be logged before exiting.
    :type message: str
    :param exit_code: The exit code to be used when terminating the program.
    :type exit_code: int
    :return: NoReturn
    :raises SystemExit: Exits the program with the specified exit code.
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
                f"Directory path '{directory}' does not exist or is not a directory"
            )
    except (TypeError, ValueError) as e:
        raise NotADirectoryError(str(e)) from e

    return directory


def get_resolution(file_name: str) -> str:
    """
    Extracts the resolution from a video file name. Not trying to be perfect here.

    Returns a string of the resolution and scan mode or if no resolution is found, returns None.

    :param file_name: The file name
    :type file_name: str
    :return: The extracted resolution or None if no resolution is found.
    :rtype: str
    """

    file_name = re.sub(r"4k|uhd", "2160p", file_name, flags=re.IGNORECASE)
    match = re.search(r"\d{3,4}[pi]", file_name, re.IGNORECASE)

    return "" if not match else match.group(0)


def get_editions(path: Path, event_number: str) -> dict[str, VideoInfo]:
    """
    Scans the given directory and extracts editions from the file names.

    Iterates over each file that starts with the supplied event_number in the
    specified directory, extracts information from the file name, and returns a
    dictionary mapping each edition to a VideoInfo object. If a file does not
    start with the event number or does not contain an edition, it is not
    included in the result.

    :param path: The directory path to scan for files.
    :type path: Path
    :param event_number: The event_number to filter by
    :type event_number: str
    :return: A dictionary mapping editions to VideoInfo objects.
    :rtype: dict[str, VideoInfo]
    """

    editions_in_folder = {}
    for file in path.glob(f"{event_number}*", case_sensitive=False):
        if file.is_file():
            info = extract_info(file, strict=False)

            if info.edition and info.event_number == event_number:
                editions_in_folder[info.edition] = info

    return editions_in_folder


def find_largest_video_file(video_path: Path) -> Path | None:
    """
    Finds the largest video file in the given path.

    Valid video file extensions are defined in VIDEO_EXTENSIONS.
    If video files are found, it returns the largest one based on file size,
    because sometimes a sample video or thumbnail is included.
    If no video files are found, returns None.

    :param video_path: The path to search for video files.
    :type video_path: Path
    :return: Path of the largest video file or None if no video files are found.
    :rtype: Path | None
    """

    if not video_path.exists() or not video_path.is_dir():
        return None

    video_files = [
        f for f in video_path.iterdir() if f.is_file() and f.suffix in VIDEO_EXTENSIONS
    ]

    if not video_files:
        return None

    return max(video_files, key=lambda f: f.stat().st_size)


def find_names(directory: Path = DESTINATION_FOLDER, event_number: str = "") -> str:
    """
    Attempts to find fighter names of a given ufc event from an existing folder.

    Searches for a folder in DESTINATION_FOLDER that starts with the event number.
    If a folder is found, it will attempt to extract the fighter names from the
    folder name. Also recursively checks inside the folder.

    This also enables a bulk rename to fix folders with missing fighter names.

    :param directory: The directory to search.
    :type directory: Path
    :param event_number: The UFC event number.
    :type event_number: str
    :return: The fighter names.
    :rtype: str
    """

    for path in directory.glob(f"{event_number}*", case_sensitive=False):
        info = extract_info(path, strict=False)

        if path.is_dir() and not info.fighter_names:
            # If the folder doesn't have fighter names, check inside
            info.fighter_names = find_names(path, event_number)

        if info.fighter_names:
            return info.fighter_names

    return ""


def extract_info(path: Path, strict: bool = True) -> VideoInfo:
    """
    Extract UFC event number, fighter names, and edition from a filename.

    Uses regex to extract the information from the filename.
    First tries to find the UFC event number. If not found and strict
    is True, the script exits. How it exits is determined by the
    STRICT_MATCHING variable.

    If fighter names are not found and strict is True, find_names()
    is called to attempt to find them from an existing folder.

    If the extraction is successful, returns a dictionary of info found.

    :param path: The path of the file to extract information from
    :type path: str
    :param strict: Whether to try hard or not
    :type strict: bool
    :return: A VideoInfo object with the extracted information
    :rtype: VideoInfo
    """

    # Unify separators to spaces
    file_name = re.sub(r"[\.\s_]", " ", path.stem)

    event_number, fighter_names, edition = "", "", ""

    info = VideoInfo(path=path)

    # Event number
    # there are also 'UFC Live' events which will not be caught, but they usually
    # don't have a number anyway
    pattern = r"ufc (?P<ppv>\d{1,4})|ufc fight night (?P<fnight>\d{1,4})|ufc on (?P<ufc_on>\w+ \d{1,4})"
    match = re.search(pattern, file_name, re.IGNORECASE)

    if not match and strict:
        if STRICT_MATCHING:
            # error exit
            exit_log(
                f"Unable to extract UFC event number from {file_name}", exit_code=1
            )
        else:
            # silent exit
            exit_log(exit_code=0)

    elif match:
        if match.group("ppv"):
            event_number = f"UFC {match.group('ppv')}"
        elif match.group("fnight"):
            event_number = f"UFC Fight Night {match.group('fnight')}"
        elif match.group("ufc_on"):
            event_number = f"UFC on {match.group('ufc_on').upper()}"
        info.event_number = event_number

    # file_name = file_name[:match.start()] + file_name[match.end():]

    # Find the rest. Using global search because sometimes they appear out of order
    pattern = (
        # Fighter names (x vs y)
        r"(?:(?<= )|(?<=^))(?P<name1>(?:(?!ppv|main|event|prelim|preliminary)[a-z-]+ )+)vs ?(?P<name2>(?:(?!ppv|main|prelim|early|web)[a-z-]+(?: |$))+)(?:(?![0-9]{2,})(?P<num>[0-9]))?"
        # NOTE: If additional words end up in the name, add them to the regex
        # Edition (not including ppv because it is often ommitted)
        r"|(?P<edition>early prelims|prelims|preliminary)"
    )

    matches = re.finditer(pattern, file_name, re.IGNORECASE)

    for match in matches:
        if match.group("name1") and match.group("name2"):
            fighter_names = f"{match.group('name1').strip().title()} vs {match.group('name2').strip().title()}"
            if match.group("num"):
                fighter_names += f" {match.group('num')}"

        if match.group("edition"):
            edition = match.group("edition")
            edition = " ".join(w.capitalize() for w in edition.split())
            # Correct weird edition names
            info.edition = {
                "Preliminary": "Prelims",
            }.get(edition, edition)
            info.edition = f"edition-{info.edition}"


    if not fighter_names and strict:
        # we need to go deeper
        fighter_names = find_names(DESTINATION_FOLDER, info.event_number)

    info.fighter_names = fighter_names

    info.resolution = get_resolution(file_name)

    return info


def construct_path(file_path: Path) -> tuple[Path, VideoInfo]:
    """
    Constructs a new file path for a UFC video file based on extracted information.

    The formatting is defined in the FORMAT_X variables.
    The fighter names and resolution may be ommitted if not found in the file name.

    :param file_path: The full path to the original video file.
    :type file_path: Path
    :return: A tuple containing the new file path and a dictionary of extracted information.
    :rtype: tuple[Path, dict[str, str]]
    """

    parts = [""] * len(FORMAT_ORDER)
    folder_parts = [""] * len(FORMAT_ORDER)

    info = extract_info(file_path)

    for field in fields(VideoInfo):
        key, value = field.name, getattr(info, field.name)

        if not value or key == "path":
            continue

        if key not in FORMAT_ORDER:
            # configuration error
            exit_log(f"FORMAT_ORDER does not contain {key}", exit_code=1)

        index = FORMAT_ORDER[key]

        if index is None:
            # part is ommitted
            continue

        token = FORMAT_TOKENS.get(key)

        if token == Bracket.CURLY:
            value = "{" + value + "}"
        elif token == Bracket.SQUARE:
            value = "[" + value + "]"

        parts[index] = value

        if key in FORMAT_FOLDER:
            folder_parts[index] = value

    # e.g. UFC Fight Night 248 Yan vs Figueiredo
    folder_name = " ".join(filter(None, folder_parts))

    # e.g. UFC Fight Night 248 Yan vs Figueiredo {edition-Main Event} [1080p].mkv
    file_name = " ".join(filter(None, parts)) + file_path.suffix

    return (DESTINATION_FOLDER / folder_name / file_name), info


def move_file(src: Path, dst: Path) -> tuple[str, int]:
    """
    Moves a file from its original location to a new location.

    :param src: The full path to the original video file.
    :type src: Path
    :param dst: The full path to the new video file.
    :type dst: Path
    :return: A tuple containing a boolean indicating success and an error message.
    :rtype: tuple[str, int]
    """

    if DRY_RUN:
        return f"Moved {src} to {dst}", 0

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"Failed to create directory {dst.parent}: {e}", 1

    try:
        shutil.move(src, dst)
    except shutil.Error as e:
        return f"Failed to move {src} to {dst}: {e}", 1

    return f"Moved {src} to {dst}", 0


def rename_and_move(file_path: Path) -> tuple[str, int]:
    """
    Renames and moves a UFC video file to a new directory based on extracted information.

    Moves the file to the new location under the DESTINATION_FOLDER directory. If the
    extraction is unsuccessful, an error message is printed and the script exits.

    :param file_path: The full path to the downloaded video file.
    :type file_path: Path
    :return: A tuple containing a boolean indicating success and an error message.
    :rtype: tuple[str, int]
    """

    # VideoInfo obj includes file_path, not new_path
    new_path, info = construct_path(file_path)

    if new_path.exists():
        # If the new file already exists, print an error and exit
        return f"File {new_path.name} already exists in {new_path.parent}", 1

    if not new_path.parent.exists():
        # folder doesn't exist so nothing else to do
        return move_file(info.path, new_path)

    # find existing video file with same edition and event number
    existing = get_editions(new_path.parent, info.event_number)

    if not existing or not existing.get(info.edition):
        # folder doesn't have this edition
        return move_file(info.path, new_path)

    # edition already exists in folder

    x_info = existing[info.edition]

    if x_info.path == file_path:
        # just a rename
        return move_file(info.path, new_path)

    # if there is no resolution in either, the new file is preferred
    new_res = int(info.resolution[:-1] or 99999)
    old_res = int(x_info.resolution[:-1] or 0)

    if new_res == old_res:
        if not REPLACE_SAME_RES:
            return (
                f"File {x_info.path.name} already exists in {new_path.parent} with the same resolution.",
                1,
            )

        if not DRY_RUN:
            x_info.path.unlink()

        print(f"Replacing {x_info.path.name} with {new_path.name}")
        return move_file(info.path, new_path)

    elif new_res < old_res:
        # If the existing file has a higher resolution, error
        return (
            f"File {x_info.path.name} already exists in {new_path.parent} with a higher resolution.",
            1,
        )

    else:
        # If the downloaded file has a higher resolution, replace the existing file
        if DRY_RUN:
            print(f"Removed lower resolution file {x_info.path.name}")
        else:
            try:
                Path(x_info.path).unlink()
                print(f"Removed lower resolution file {x_info.path.name}")
            except OSError as e:
                print(f"Error deleting file: {e}")

        return move_file(info.path, new_path)


def parse_args():
    """
    Parses command line arguments. Only called if sys.argv[1] is not a directory.

    Mostly made this for re-organization of existing files. Can use arguments
    to run manually. Quick run: python ufc.py -d /path/to/downloaded/folder

    :return: The folder containing the video files.
    :rtype: any
    """

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d",
        "--dir",
        default=DESTINATION_FOLDER,
        help="The directory containing the video files to be processed",
    )
    parser.add_argument(
        "-c",
        "--category",
        help="The category of the download. If it matches UFC_CATEGORY, STRICT_MATCHING will be set to True",
    )
    parser.add_argument(
        "-D", "--dest", help="The destination folder for the renamed files"
    )
    parser.add_argument(
        "-r",
        "--replace-same-res",
        action="store_true",
        help="Replace existing files with the same resolution in the name",
    )
    parser.add_argument(
        "-s",
        "--strict-matching",
        action="store_true",
        help="Fail if the event number cannot be found in the file name",
    )
    parser.add_argument(
        "--rename-all",
        action="store_true",
        help="Rename all UFC folders and files in the directory. Use with caution.",
    )
    parser.add_argument(
        "--remove-renamed",
        action="store_true",
        help="Remove empty folders after renaming.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print out the new filenames without actually moving the files.",
    )
    args = parser.parse_args()

    if args.dest:
        globals()["DESTINATION_FOLDER"] = args.dest

    if args.replace_same_res:
        globals()["REPLACE_SAME_RES"] = True

    if args.strict_matching or args.category == UFC_CATEGORY:
        globals()["STRICT_MATCHING"] = True

    if args.dry_run:
        globals()["DRY_RUN"] = True

    directory = args.dir

    if not args.rename_all:
        return directory

    try:
        directory = check_path(directory)
    except NotADirectoryError as e:
        exit_log(str(e), exit_code=1)

    # rename all UFC folders and files in given directory
    dirs = [d for d in directory.iterdir() if d.is_dir()]

    for folder in dirs:
        if folder.is_dir():
            renamed = True  # so that we don't try to delete if there was an error

            for file in folder.iterdir():
                if file.is_file() and file.suffix in VIDEO_EXTENSIONS:
                    message, exit_code = rename_and_move(file)

                    print("Error: " + message if exit_code else message)

                    if exit_code:
                        renamed = False

            if renamed and args.remove_renamed and (len(list(folder.iterdir())) == 0):
                if args.DRY_RUN:
                    print(f"Removing empty folder {folder}")
                else:
                    folder.rmdir()

    exit_log("Done.", exit_code=0)


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

    directory, category = None, None

    if len(sys.argv) == 1:
        exit_log("Not enough arguments.", exit_code=1)

    if len(sys.argv) == 2:
        # only a job path is provided
        directory = sys.argv[1]

    elif os.getenv("SAB_VERSION"):
        # running from SABnzbd
        # Print newlines so the 'more' button is available in sabnzbd
        print("\n\n")
        directory = os.getenv("SAB_COMPLETE_DIR")
        category = os.getenv("SAB_CAT")

        if not directory or not category:
            exit_log("SAB_COMPLETE_DIR or SAB_CAT not set.", exit_code=1)

    else:
        # running manually
        directory = parse_args()

    try:
        directory = check_path(directory)
    except NotADirectoryError as e:
        exit_log(f"Invalid job directory: {e}", exit_code=1)

    if category == UFC_CATEGORY:
        globals()["STRICT_MATCHING"] = True

    # Filter video files
    video_file = find_largest_video_file(directory)

    if not video_file:
        exit_log("No video files found.", exit_code=1)

    exit_log(*rename_and_move(video_file))


main()

sys.exit(0)
