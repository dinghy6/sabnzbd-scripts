  

# UFC File Organizer

  

======================

A configurable Python script used in SABnzbd's post-processing to move and rename UFC files.


## Description

Plex uses editions to differentiate versions of a movie. This can be used to separate and specify in plex whether the UFC 'movie' is `Main Event`, `Prelims`, or `Early Prelims`.

This script attempts to get the UFC event number, fighter names, and edition from a filename and creates a new folder in the specified destination folder. It then moves the file to this new folder and renames it to include the event number, fighter names, edition and resolution. The fighter names and resolution are only added if found, otherwise ignored.

Subfolders are supported if configured in the `SUB_FOLDER` variable. Subfolders are for the Prelims and Early Prelims. Due to the way Plex detects movies and "extras", the Prelims and Early Prelims will not be detected if they are in a subfolder until the Main Event is also downloaded (which will be placed in the main folder for that event).


## Features

* Extracts UFC event number, fighter names, edition and resolution from filename.
* Creates new folders (and optionally subfolders) in the destination folder.
* Automatically inherits permissions and ownership from the destination folder.
* Gets the job path and job category from SABnzbd
* Moves the file to its new home and renames it to include the event number, fighter names, edition and resolution.
* Resolves conflicts by comparing resolutions. Replaces lower res with higher, etc.
* Can do a bulk renaming to re-organize existing UFC libraries in the destination to the configured format
	* Even supports moving from having subfolders to no subfolders and vice versa
* Fully customizable naming scheme (see [[#Formatting]])


## Configuration

### Constants

These define various behaviours of the script. The type is explicitly specified in the code, so make sure you keep the values valid.

* `DESTINATION_FOLDER`: The folder where the new folders will be created. The owner and permissions are also inherited from this folder so make sure these are correct.
* `SUB_FOLDER`: Whatever this is set to (for example `"Other"`) will be the name of the subfolder that the Prelims and Early Prelims go in. The Main Event will be in the parent folder. If this is set to `None` or `""`, there won't be a subfolder.
* `UFC_CATEGORY`: The category name for UFC files. This category is assumed to be all UFC files and will fail the download if the file names can't be parsed.
* `REPLACE_SAME_RES`: Whether to replace existing files that have the same resolution as the downloaded file. The script will consider existing files for the same UFC event, edition and resolution as an error and not change the existing file.
	* If the full path and name for the new file is exactly the same as what's existing, there'll be an error. This should only happen when you run a bulk rename and these errors just mean no renaming/moving needs to be done.
* `STRICT_MATCHING`: Whether to error out if the event number can't be found (configuration is ignored and set to `True` if the job category name matches `UFC_CATEGORY`).
* `DRY_RUN`: If set to `True`, the script won't make any changes but will just print out what changes would be made (some things won't be printed out due to being unknown until tried).
* `VIDEO_EXTENSIONS`: Defines the valid extensions the script will deal with. Anything not in this list will be ignored.


### Formatting

The format the script uses to make and rename files and folders can be customized. The script can also rename existing libraries to the customized format (see [[#Usage]]).

Important notes:
 - The `event_number` should always be first (with a value of `0`)
 - For Plex to pick up the correct edition, `Bracket.CURLY` should be set for `edition`
 - Adding brackets to `fighter_names` will mess up the regexes for detecting them. this may be fixed later
 - The keys must match the attributes of `VideoInfo` (but don't include `path`). These can be seen just below the formatting section and are already filled in as the default values.

`FORMAT_ORDER` - The values for each part is the order that they will be in the folder name and file name, starting with `event_number` at `0`.

`FORMAT_TOKENS` - Can specify what brackets are used for each part (read notes above)

`FORMAT_FOLDER` - Whatever is in here will be included in the folder name. If `edition` is included, don't use subfolders because the main event will be in a different parent folder.


## Usage

### SABnzbd Post-Processing
See more information on SABnzbd scripts [here](https://sabnzbd.org/wiki/configuration/4.3/scripts/post-processing-scripts).

1. Place the script in your SABnzbd scripts directory
2. Set the category the script should run on. (It's best to make a category that takes `TV > Sport` files specifically, but sometimes UFC events are categorized as `Movies*`)
3. Configure the other variables to your liking
4. In order for the script to mark the download as failed, the `Post-processing script can flag job as failed` switch must be on (under Config > Switches > Post processing).

### Standalone
Can run on its own with arguments (run `ufc.py -h` for more info)
Useful commands:
 - `ufc.py --rename-all --remove-empty`: This finds all the UFC files in the destination directory and organizes them into the configured format. This can be used to apply the current formatting to all existing UFC files. Empty folders will be removed.
	 - should run this first with `--dry-run` to see the changes that will be made
   - `ufc.py /path/to/job`: This runs a rename and move on the supplied directory.
   - `ufc.py -d /path/to/job -c ufc`: The job directory is passed with `-d` and the job category is passed with `-c`. Can also use `--dir="/path" --category="ufc"`.


## Requirements

* Python 3.9+
*  Modules: `os`, `sys`, `re`, `argparse`, `shutil`, `dataclasses`, `pathlib`, `enum`, `typing`


## Notes

* This script is designed to work with SABnzbd's post-processing feature but can be modified easily. It just needs the directory of the finished job and the category of the job. Those can also be supplied via the cli if called by another script or program.

* The script assumes that the video file wanted is the largest file in the given directory

* The script uses regex to extract info from the filename, so things may go wrong. It's pretty good so far though.