import os
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import logging
import requests
import argparse
import time

# Base directory where all movies are stored (default)
BASE_MOVIE_DIR = '/srv/LibraryPart/Library/Movies'
NFO_DIR = '/media/NAS/Library/Movies'  # Default NFO directory
OUTPUT_DIR = '/home/nix/Downloads/Collections'  # Default output directory for collection XMLs
TMDB_API_KEY = ''  # Add your TMDb API key, or leave it empty to disable TMDb fetching

# Supported video extensions
VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv']

# Throttling API calls to 1 every 2 seconds
THROTTLE_TIME = 2  # seconds

def parse_movie_nfo(nfo_file):
    """Parses the movie NFO to extract relevant collection and file information."""
    tree = ET.parse(nfo_file)
    root = tree.getroot()

    data = {}
    data['LocalTitle'] = root.findtext('title', default='Unknown Title')
    data['TmdbId'] = root.findtext('tmdbid', default='Unknown')
    data['CollectionName'] = root.findtext('set/name', default=None)
    data['Overview'] = root.findtext('plot', default='No overview available.')
    data['OriginalFile'] = root.findtext('original_filename', default=None)

    # Extract genres and studios
    data['Genres'] = [genre.text for genre in root.findall('genre')]  # List of genres
    data['Studios'] = [studio.text for studio in root.findall('studio')]  # List of studios

    return data

def create_collection_xml(collection_name, collection_data, output_file):
    """Creates a collection XML file with the gathered data."""
    root = ET.Element("Item")

    # Basic information about the collection
    ET.SubElement(root, "ContentRating").text = "NR"  # Placeholder for Content Rating
    ET.SubElement(root, "LockData").text = "false"
    ET.SubElement(root, "Overview").text = collection_data['Overview']
    ET.SubElement(root, "LocalTitle").text = collection_name
    ET.SubElement(root, "DisplayOrder").text = "PremiereDate"

    # Genres
    genres_elem = ET.SubElement(root, "Genres")
    for genre in collection_data.get('Genres', []):
        ET.SubElement(genres_elem, "Genre").text = genre

    # Studios
    studios_elem = ET.SubElement(root, "Studios")
    for studio in collection_data.get('Studios', []):
        ET.SubElement(studios_elem, "Studio").text = studio

    # Collection Items (file paths)
    collection_items = ET.SubElement(root, "CollectionItems")
    for movie in collection_data['Movies']:
        collection_item = ET.SubElement(collection_items, "CollectionItem")
        ET.SubElement(collection_item, "Path").text = movie['Path']

    # Pretty-print the XML
    xml_str = ET.tostring(root, encoding='utf-8')
    dom = minidom.parseString(xml_str)
    pretty_xml_as_string = dom.toprettyxml(indent="  ")

    # Save the formatted XML string to a file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(pretty_xml_as_string)

    logging.info(f"Collection XML saved to {output_file}")

def fetch_collection_data_from_tmdb(tmdb_id):
    """Fetches collection metadata from TMDb for a given collection."""
    if not TMDB_API_KEY:
        logging.info("No TMDb API key provided. Skipping TMDb fetch.")
        return 'No overview available.'

    try:
        time.sleep(THROTTLE_TIME)  # Throttle API calls
        collection_info = requests.get(f"https://api.themoviedb.org/3/collection/{tmdb_id}?api_key={TMDB_API_KEY}").json()
        
        if collection_info:
            overview = collection_info.get('overview', 'No overview available.')
            return overview
        else:
            logging.warning(f"No collection data found for TMDb ID {tmdb_id}")
            return 'No overview available.'
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching collection data from TMDb for ID {tmdb_id}: {e}")
        return 'No overview available.'

def find_video_file_for_nfo(nfo_file_path):
    """Finds a video file in the same directory as the .nfo file with a matching base filename."""
    nfo_dir = os.path.dirname(nfo_file_path)
    nfo_base = os.path.splitext(os.path.basename(nfo_file_path))[0]

    # Search for matching video files
    for ext in VIDEO_EXTENSIONS:
        video_file_path = os.path.join(nfo_dir, nfo_base + ext)
        if os.path.exists(video_file_path):
            return video_file_path
    return None

def process_movie_nfo_files(nfo_dir, output_dir, overwrite=False):
    """Scans movie NFOs and builds collection XMLs based on the movie's collection information."""
    collections = {}

    # Traverse the NFO directory to find all NFO files
    for root, dirs, files in os.walk(nfo_dir):
        for file in files:
            if file.endswith('.nfo'):
                nfo_file_path = os.path.join(root, file)

                # Parse the movie NFO
                movie_data = parse_movie_nfo(nfo_file_path)

                if movie_data['CollectionName']:
                    # Clean up the collection name for folder naming
                    collection_name = movie_data['CollectionName'].replace('/', ' - ')  # Replace '/' with ' - '

                    # Find the video file that matches the NFO
                    video_file = find_video_file_for_nfo(nfo_file_path)

                    if not video_file:
                        logging.warning(f"No matching video file found for NFO: {nfo_file_path}")
                        continue

                    # Convert the video file's path to be relative to the base movie directory
                    movie_relative_path = os.path.relpath(video_file, BASE_MOVIE_DIR)

                    # Add the movie to its collection
                    if collection_name not in collections:
                        collections[collection_name] = {
                            'Overview': fetch_collection_data_from_tmdb(movie_data['TmdbId']),
                            'Movies': [],
                            'Genres': movie_data['Genres'],  # Add genres from the movie
                            'Studios': movie_data['Studios'],  # Add studios from the movie
                        }
                    collections[collection_name]['Movies'].append({
                        'Path': os.path.join(BASE_MOVIE_DIR, movie_relative_path)
                    })

    # Now create collection.xml for each collection
    for collection_name, collection_data in collections.items():
        # Create the output folder for the collection
        output_folder = os.path.join(output_dir, f"{collection_name} [Boxset]")
        os.makedirs(output_folder, exist_ok=True)

        # Generate the collection XML file
        output_file = os.path.join(output_folder, 'collection.xml')
        if overwrite or not os.path.exists(output_file):
            create_collection_xml(collection_name, collection_data, output_file)
        else:
            logging.info(f"Collection XML for '{collection_name}' already exists. Skipping.")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    # Set up argument parsing
    parser = argparse.ArgumentParser(description="Generate collection XMLs from movie NFO files.")
    parser.add_argument('--base_movie_dir', default=BASE_MOVIE_DIR, help='Base directory where all movies are stored.')
    parser.add_argument('--nfo_dir', default=NFO_DIR, help='Directory where NFO files are located.')
    parser.add_argument('--output_dir', default=OUTPUT_DIR, help='Directory where collection XMLs will be saved.')
    parser.add_argument('--overwrite', action='store_true', help='Overwrite existing collection XMLs.')
    args = parser.parse_args()

    # Use the arguments if provided, otherwise use defaults
    BASE_MOVIE_DIR = args.base_movie_dir
    NFO_DIR = args.nfo_dir
    OUTPUT_DIR = args.output_dir

    process_movie_nfo_files(NFO_DIR, OUTPUT_DIR, args.overwrite)
