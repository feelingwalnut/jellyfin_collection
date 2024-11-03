Create collection XML files from NFOs.

if no api key is provided, will use local information from movie nfo files to fill the collection xml.
if api key provided, will fill xml missing fields with information obtained from api as well as fetch one banner and one poster image (with preference for english)

usage: 
collectionmaker.py --library_dir [LIBRARY_DIR] --output_dir [OUTPUT_DIR] --key [KEY] --overwrite

options:

  --library_dir [LIBRARY_DIR]
  Required, Directory containing NFO and video files.
  
  --output_dir [OUTPUT_DIR]
  Optional, defaults to /var/lib/jellyfin/data/collections, Output directory for collection XMLs.
  
  --key [KEY]
  Optional, TMDb API key for fetching additional collection data/images
  
  --overwrite
  Optional, Overwrite existing XML files.
