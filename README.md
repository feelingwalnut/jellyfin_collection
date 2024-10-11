python your_script.py --nfo_dir "/path/to/nfo_directory" --base_movie_dir "/mnt/movies" --output_dir "/mnt/collections" --overwrite


Breakdown of the command:
    --NFO_Dir "path/to/NFO": specify if NFO's are not in same directory/subdirecotry as script.
    --base_movie_dir "/mnt/movies": Specifies the base hierarchy for the movies. If not provided, the default directory (NFO's location) is used.
    --output_dir "/mnt/collections": Specifies where to save the collection.xml files. If not provided, the default directory for jellyfin, from the script is used.
    --overwrite: This flag forces the script to overwrite any existing collection.xml files
