# UFC File Organizer

======================

A configurable Python script used in SABnzbd's post-processing to move and rename UFC files.

## Description

Plex uses editions to differentiate versions of a movie. This can be used to separate and specify in Plex whether the UFC 'movie' is `Main Event`, `Prelims`, or `Early Prelims`.

This script attempts to get the UFC event number, fighter names, and edition from a filename and creates a new folder in the specified destination folder. It then moves the file to this new folder and renames it. The renaming scheme and folder structure can be customized. The fighter names and resolution are only added if found, otherwise ignored.

Subfolders are supported if configured in the `subfolder` variable. If configured, the Prelims and Early Prelims will be placed in the subfolder. Due to the way Plex detects movies and "extras", the Prelims and Early Prelims will not be detected if they are in a subfolder until the Main Event is also downloaded (which will be placed in the main folder for that event).

## Features

* Extracts UFC event number, fighter names, edition, and resolution from filename.
* Creates new folders (and optionally subfolders) in the destination folder.
* Applies minimum permissions 770 for folders and 660 for files. Can configure a higher minimum if you want (default in ini is 775 and 664).
* Gets the job path and job category from SABnzbd.
* Moves the file to its new home and renames it according to configuration
* Resolves conflicts by comparing resolutions: replaces lower res with higher, doesn't replace same res unless configured to, won't replace higher res.
* Can do a bulk renaming to re-organize existing UFC libraries in the destination to the configured format. Can also do a force refresh on permissions for all files/folders.
  * Even supports moving from having subfolders to no subfolders and vice versa.
* Fully customizable naming scheme (see [Formatting](#formatting)).

## Configuration

### Paths

* `destination_folder`: The folder where the new folders will be created. The script user is checked against this folder and if the script is run as root, the owner for new files/folders will be inherited from this folder.
* `subfolder`: Whatever this is set to (for example `"Other"`) will be the name of the subfolder that the Prelims and Early Prelims go in. The Main Event will be in the parent folder. If this is set to `None` or `""`, there won't be a subfolder.

### Categories
* `ufc_category`: The category name for UFC files. This category is assumed to be all UFC files and will fail the download if the file names can't be parsed.
* `strict_matching`: Whether to error out if the event number can't be found (configuration is ignored and set to `True` if the job category name matches `ufc_category`).

### File Handling
* `dry_run`: If set to `True`, the script won't make any changes but will just print out what changes would be made (some things won't be printed out due to being unknown until tried).
* `replace_same_res`: Whether to replace existing files that have the same resolution as the downloaded file. The script will consider existing files for the same UFC event, edition, and resolution as an error and not change the existing file.
  * If the full path and name for the new file is exactly the same as what's existing, there'll be an error. This should only happen when you run a bulk rename and these errors just mean no renaming/moving needs to be done.
* `video_extensions`: Defines the valid extensions the script will deal with. Anything not in this list will be ignored.
* `file_permissions`: The permissions to set for files. The script will set file permissions to at least 660. If this is set higher, this will be used instead.
* `folder_permissions`: The permissions to set for folders. The script will set folder permissions to at least 770. If this is set higher, this will be used instead.

### Formatting

The format the script uses to make and rename files and folders can be customized. The script can also rename existing libraries to the customized format (see [Usage](#usage)).

Valid parts:
 - `event_number` (includes the whole event name, e.g. `UFC Fight Night 248`)
 - `fighter_names`
 - `edition`
 - `resolution`

#### Format.Order
 - The values for each part is the order that they will be in for all formatting.
 - The `event_number` should always be first (with a value of `0`).
 - Set a value here to `None` to not include that value in any formatting. **Note:** Excluding information means that info is lost. It's best to leave everything here then configure the other options.

#### Format.Tokens
 - Can specify what brackets surround each part. Options are `CURLY`, `SQUARE` or `ROUND`. Only applies brackets if they are specified, otherwise no brackets are used for that part.
 - For Plex to pick up the correct edition, `CURLY` should be set for `edition`.
 - Adding brackets to `fighter_names` will mess up the regexes for detecting them. This may be fixed later.

#### Format.Folder
 - Specify which parts should be in the main folder name.
 - If using a subfolder, limit this to just the event name and fighter names (the fighter names aren't required but look nice). Otherwise the subfolder will probably be placed in the wrong folder and things will go wrong.
 	- For example, if `edition` is included, then each edition will go to it's own folder. If a subfolder is set, a subfolder will be created in the Prelims folders but there won't be anything else in it so plex won't see it.
- If the resolution is included, it will be a mess of different folders and wont be cleaned up until the format is corrected and a bulk rename is ran.

#### Format.Subfolder
 - Specifies which parts will be in the filename of the files that are put inside a subfolder.
 - This is so that what plex shows in the extras can be a shorter filename if you want.
 - Does nothing if subfolder is not set.

## Usage

The `ufc.ini.template` file should be renamed. The script looks for `ufc.ini` first, but falls back to the template. Read the configuration options above (or in the ini) and change them to suit you.

### SABnzbd Post-Processing

See more information on SABnzbd scripts [here](https://sabnzbd.org/wiki/configuration/4.3/scripts/post-processing-scripts).

1. Place the script in your SABnzbd scripts directory. Or run `git clone https://github.com/dinghy6/sabnzbd-scripts.git` while cd'd in the script directory.
2. Set the category the script should run on. (It's best to make a category that takes `TV > Sport` files specifically, but sometimes UFC events are categorized as `Movies*`).
3. In order for the script to mark the download as failed, the `Post-processing script can flag job as failed` switch must be on (under Config > Switches > Post processing).

### Standalone

Can run on its own with arguments (run `ufc.py -h` for more info). Still should configure teh ufc

Useful commands:
 - `ufc.py --rename-all --remove-empty`: This finds all the UFC files in the destination directory and organizes them into the configured format. This can be used to apply the current formatting to all existing UFC files. Empty folders will be removed.
  - Should run this first with `--dry-run` to see the changes that will be made.
 - `ufc.py --rename-all --refresh-perms`: Runs a bulk rename and checks all permissions while doing it. If they aren't correct, they'll be (try to be) fixed.
 - `ufc.py /path/to/job`: This runs a rename and move on the supplied directory.
 - `ufc.py -d /path/to/job -c ufc`: The job directory is passed with `-d` and the job category is passed with `-c`. Can also use `--dir="/path" --category="ufc"`.

## Requirements

* Python 3.10+
* Modules: `os`, `sys`, `re`, `stat`, `enum`, `shutil`, `argparse`, `pathlib`, `typing`, `dataclasses`, `configparser`

## Notes

* This script is designed to work with SABnzbd's post-processing feature but can be modified easily. It just needs the directory of the finished job and the category of the job. Those can also be supplied via the CLI if called by another script or program.
* The script assumes that the video file wanted is the largest file in the given directory.
* The script uses regex to extract info from the filename, so things may go wrong. It's pretty good so far though.
