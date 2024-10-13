import os
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import logging
import requests
import argparse
import time
import re
import json
import gzip

# Base directory where all movies are stored (default)
BASE_MOVIE_DIR = '/srv/LibraryPart/Library/Movies'
NFO_DIR = '/media/NAS/Library/Movies'  # Default NFO directory
OUTPUT_DIR = '/var/lib/jellyfin/data/collections'  # Default output directory for collection XMLs
TMDB_API_KEY = ''  # Add your TMDb API key, or leave it empty to disable TMDb fetching

# Supported video extensions
VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.webm', '.m4v']

# Throttling API calls
THROTTLE_TIME = 0.1  # seconds

# Global flag for TMDb fetch warning
tmdb_warning_flag = True

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

def fetch_collection_data_from_tmdb(tmdb_id, movie_data):
    """Fetches collection metadata from TMDb for a given collection."""
    global tmdb_warning_flag

    if not TMDB_API_KEY:
        if tmdb_warning_flag:
            logging.info("No TMDb API key provided. Skipping TMDb fetch.")
            tmdb_warning_flag = False
        return {'Overview': movie_data['Overview'], 'Genres': [], 'Studios': []}

    try:
        time.sleep(THROTTLE_TIME)  # Throttle API calls
        collection_info = requests.get(f"https://api.themoviedb.org/3/collection/{tmdb_id}?api_key={TMDB_API_KEY}").json()
        
        if collection_info:
            return {
                'Overview': collection_info.get('overview', 'No overview available.'),
                'Genres': [genre['name'] for genre in collection_info.get('genres', [])],
                'Studios': [studio['name'] for studio in collection_info.get('production_companies', [])]
            }
        else:
            logging.warning(f"No collection data found for TMDb ID {tmdb_id}")
            return {'Overview': 'No overview available.', 'Genres': [], 'Studios': []}
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching collection data from TMDb for ID {tmdb_id}: {e}")
        return {'Overview': 'No overview available.', 'Genres': [], 'Studios': []}

def extract_date_from_filename(filename):
    """Extracts the date from the filename in the format 'movie (YYYY-MM-DD).ext'."""
    match = re.search(r'\((\d{4}-\d{2}-\d{2})\)', filename)
    if match:
        return match.group(1)
    return None  # Return None if no date found

def sort_movies_by_date(movies):
    """Sorts a list of movies based on the extracted date from their filenames."""
    return sorted(movies, key=lambda m: extract_date_from_filename(os.path.basename(m['Path'])) or '')

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

def fetch_collection_ids():
    """Fetches the current list of collection IDs from the TMDb export file."""
    current_date = time.strftime("%m_%d_%Y")  # Format date as MM_DD_YYYY
    url = f"http://files.tmdb.org/p/exports/collection_ids_{current_date}.json.gz"

    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses

        # Write the .gz file
        gz_file_path = 'collection_ids.json.gz'
        with open(gz_file_path, 'wb') as f:
            f.write(response.content)

        # Extract the JSON from the gzipped file
        with gzip.open(gz_file_path, 'rt', encoding='utf-8') as f:
            collection_ids = json.load(f)

        return collection_ids
    except Exception as e:
        logging.error(f"Failed to fetch or extract collection IDs: {e}")
        return []

def process_movie_nfo_files(nfo_dir, output_dir, overwrite=False):
    """Scans movie NFOs and builds collection XMLs based on the movie's collection information."""
    collections = {}

    # Fetch collection IDs from TMDb
    collection_ids = fetch_collection_ids()

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

                    # Add the movie to its collection only if the collection ID is in the fetched IDs
                    if movie_data['TmdbId'] in collection_ids:
                        if collection_name not in collections:
                            collections[collection_name] = {
                                'Overview': movie_data['Overview'],
                                'Movies': [],
                                'Genres': [],  # Start with empty genres
                                'Studios': [],  # Start with empty studios
                            }

                        collections[collection_name]['Movies'].append({'Path': movie_relative_path})

    # Create XML files for each collection, but only if there are 2 or more movies
    for collection_name, collection_data in collections.items():
        if len(collection_data['Movies']) >= 2:
            # Fetch additional data from TMDb
            collection_info = fetch_collection_data_from_tmdb(collection_data['Movies'][0]['TmdbId'], collection_data)
            collection_data['Overview'] = collection_info['Overview']
            collection_data['Genres'] = collection_info.get('Genres', [])
            collection_data['Studios'] = collection_info.get('Studios', [])

            # Sort movies by date before creating the XML
            collection_data['Movies'] = sort_movies_by_date(collection_data['Movies'])

            collection_dir = os.path.join(output_dir, collection_name)

            if not os.path.exists(collection_dir):
                os.makedirs(collection_dir)

            output_file = os.path.join(collection_dir, 'collection.xml')

            if not os.path.exists(output_file) or overwrite:
                create_collection_xml(collection_name, collection_data, output_file)
        else:
            logging.info(f"Skipping collection '{collection_name}' as it contains less than 2 movies.")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description='Process movie NFO files and generate collection XMLs.')
    parser.add_argument('--nfo_dir', default=NFO_DIR, help='Directory containing movie NFO files.')
    parser.add_argument('--output_dir', default=OUTPUT_DIR, help='Output directory for collection XMLs.')
    parser.add_argument('--overwrite', action='store_true', help='Overwrite existing XML files.')

    args = parser.parse_args()

    process_movie_nfo_files(args.nfo_dir, args.output_dir, args.overwrite)
