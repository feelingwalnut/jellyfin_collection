import os
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import logging
import requests
import time
import argparse

# Default directories
BASE_MOVIE_DIR = '/srv/LibraryPart/Library/Movies'
NFO_DIR = '/media/NAS/Library/Movies'
OUTPUT_DIR = '/home/nix/Downloads/Collections'
TMDB_API_KEY = ''  # Add your TMDb API key, or leave it empty to disable TMDb fetching
VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv']

# Argument parser to handle optional shell variables
parser = argparse.ArgumentParser()
parser.add_argument('--base_movie_dir', default=None, help='Base directory where movies are stored.')
parser.add_argument('--output_dir', default=None, help='Directory where collection.xml files are saved.')
parser.add_argument('--overwrite', action='store_true', help='Overwrite existing collection XML files.')
args = parser.parse_args()

# Use provided directories if given, otherwise use defaults
BASE_MOVIE_DIR = args.base_movie_dir or BASE_MOVIE_DIR
OUTPUT_DIR = args.output_dir or OUTPUT_DIR

def throttle_api_call():
    """Throttle API calls to one every two seconds."""
    time.sleep(2)

def parse_movie_nfo(nfo_file):
    """Parses the movie NFO to extract relevant collection and file information."""
    tree = ET.parse(nfo_file)
    root = tree.getroot()

    data = {
        'LocalTitle': root.findtext('title', default='Unknown Title'),
        'TmdbId': root.findtext('tmdbid', default='Unknown'),
        'CollectionName': root.findtext('set/name', default=None),
        'Overview': root.findtext('plot', default='No overview available.'),
        'OriginalFile': root.findtext('original_filename', default=None),
        'Genres': [genre.text for genre in root.findall('genre')],
        'Studios': [studio.text for studio in root.findall('studio')]
    }
    return data

def create_collection_xml(collection_name, collection_data, output_file):
    """Creates a collection XML file with the gathered data."""
    root = ET.Element("Item")
    ET.SubElement(root, "ContentRating").text = "NR"
    ET.SubElement(root, "LockData").text = "false"
    ET.SubElement(root, "Overview").text = collection_data['Overview']
    ET.SubElement(root, "LocalTitle").text = collection_name
    ET.SubElement(root, "DisplayOrder").text = "PremiereDate"

    genres_elem = ET.SubElement(root, "Genres")
    for genre in collection_data.get('Genres', []):
        ET.SubElement(genres_elem, "Genre").text = genre

    studios_elem = ET.SubElement(root, "Studios")
    for studio in collection_data.get('Studios', []):
        ET.SubElement(studios_elem, "Studio").text = studio

    collection_items = ET.SubElement(root, "CollectionItems")
    for movie in collection_data['Movies']:
        collection_item = ET.SubElement(collection_items, "CollectionItem")
        ET.SubElement(collection_item, "Path").text = movie['Path']

    xml_str = ET.tostring(root, encoding='utf-8')
    dom = minidom.parseString(xml_str)
    pretty_xml = dom.toprettyxml(indent="  ")

    if os.path.exists(output_file) and not args.overwrite:
        logging.info(f"File {output_file} already exists. Skipping.")
    else:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(pretty_xml)
        logging.info(f"Collection XML saved to {output_file}")

def fetch_collection_data_from_tmdb(tmdb_id):
    """Fetches collection metadata from TMDb for a given collection."""
    if not TMDB_API_KEY:
        logging.info("No TMDb API key provided. Skipping TMDb fetch.")
        return 'No overview available.'

    try:
        throttle_api_call()
        collection_info = requests.get(f"https://api.themoviedb.org/3/collection/{tmdb_id}?api_key={TMDB_API_KEY}").json()
        return collection_info.get('overview', 'No overview available.')
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching collection data from TMDb for ID {tmdb_id}: {e}")
        return 'No overview available.'

def find_video_file_for_nfo(nfo_file_path):
    """Finds a video file in the same directory as the .nfo file with a matching base filename."""
    nfo_dir = os.path.dirname(nfo_file_path)
    nfo_base = os.path.splitext(os.path.basename(nfo_file_path))[0]

    for ext in VIDEO_EXTENSIONS:
        video_file_path = os.path.join(nfo_dir, nfo_base + ext)
        if os.path.exists(video_file_path):
            return video_file_path
    return None

def process_movie_nfo_files(nfo_dir, output_dir):
    """Scans movie NFOs and builds collection XMLs based on the movie's collection information."""
    collections = {}

    for root, _, files in os.walk(nfo_dir):
        for file in files:
            if file.endswith('.nfo'):
                nfo_file_path = os.path.join(root, file)
                movie_data = parse_movie_nfo(nfo_file_path)

                if movie_data['CollectionName']:
                    collection_name = movie_data['CollectionName'].replace('/', ' - ')
                    video_file = find_video_file_for_nfo(nfo_file_path)

                    if not video_file:
                        logging.warning(f"No matching video file found for NFO: {nfo_file_path}")
                        continue

                    movie_relative_path = os.path.relpath(video_file, BASE_MOVIE_DIR or os.path.dirname(nfo_file_path))
                    if collection_name not in collections:
                        collections[collection_name] = {
                            'Overview': fetch_collection_data_from_tmdb(movie_data['TmdbId']),
                            'Movies': [],
                            'Genres': movie_data['Genres'],
                            'Studios': movie_data['Studios'],
                        }
                    collections[collection_name]['Movies'].append({'Path': movie_relative_path})

    for collection_name, collection_data in collections.items():
        output_folder = os.path.join(output_dir, f"{collection_name} [Boxset]")
        os.makedirs(output_folder, exist_ok=True)

        output_file = os.path.join(output_folder, 'collection.xml')
        create_collection_xml(collection_name, collection_data, output_file)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    process_movie_nfo_files(NFO_DIR, OUTPUT_DIR)
