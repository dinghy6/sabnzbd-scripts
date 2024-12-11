  
  

# UFC File Organizer

======================
  
A Python script used in SABnzbd's post-processing to move and rename UFC files.


## Description

Plex uses editions to differentiate versions of a movie. This can be used to separate and specify in plex whether the UFC 'movie' is `Main Event`, `Prelims`, or `Early Prelims`.

This script attempts to get the UFC event number, fighter names, and edition from a filename and creates a new folder in the specified destination folder. It then moves the file to this new folder and renames it to include the event number, fighter names, edition and resolution. The fighter names and resolution are only added if found, otherwise ignored.


## Features

* Extracts UFC event number, fighter names, and edition from filename.
* Creates a new folder in the destination folder with the event number, fighter names and edition
* Moves the file to the new folder and renames it to include the event number, fighter names, edition and resolution.
* Resolves conflicts by comparing video file resolutions. Replaces lower res with higher, etc.


## Configuration

* `DESTINATION_FOLDER`: The folder where the new folders and files will be created
* `REPLACE_SAME_RES`: Whether to replace existing files that have the same resolution as the downloaded file
* `STRICT_MATCHING`: Whether to error out if the event number can't be found (set to `True` if the category name is `UFC_CATEGORY`)
* `UFC_CATEGORY`: The category name for UFC files. This category is assumed to be all UFC files and will fail the download if the file names can't be parsed.


## Usage

See more information on SABnzbd scripts [here](https://sabnzbd.org/wiki/configuration/4.3/scripts/post-processing-scripts).

1. Place the script in your SABnzbd scripts directory
2. Set the category the script should run on. (It's best to make a category that takes TV > Sport files specifically, but sometimes UFC events are categorized as Movies*)
3. Configure the variables as explained above: `DESTINATION_FOLDER`, `REPLACE_SAME_RES`, `STRICT_MATCHING`, and `UFC_CATEGORY` variables
4. In order for the script to mark the download as failed, the `Post-processing script can flag job as failed` switch must be on (under Config > Switches > Post processing). 


## Requirements

* Python 3.9+
* `re`, `shutil` and `pathlib` modules


## Notes

* This script is designed to work with SABnzbd's post-processing feature but can be modified easily. It just needs the directory of the finished job and the category of the job.
* The script assumes that the video file wanted is the largest file in the given directory
* The script uses a large regex to extract info from the filename, so things may go wrong. It's pretty good so far though.