Create collection XML files from NFOs.

if no api key is provided, will use local information from movie nfo files to fill the collection xml.
if api key provided, will fill xml missing fields with information obtained from api as well as fetch one banner and one poster image (with preference for english)

usage: collectionmaker.py -h --library_dir [LIBRARY_DIR] --output_dir [OUTPUT_DIR] --key [KEY] --overwrite
options:
  -h, --help                   show this help message and exit
  --library_dir [LIBRARY_DIR]  Directory containing NFO and video files.
  --output_dir [OUTPUT_DIR]    Output directory for collection XMLs.
  --key [KEY]                    TMDb API key for fetching additional collection data/images
  --overwrite                  Overwrite existing XML files.
