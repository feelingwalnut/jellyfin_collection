import os
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import logging
import requests
import argparse
import time
import gzip
import json
from datetime import datetime

# Supported video extensions
VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.webm', '.m4v']

# Throttling API calls
THROTTLE_TIME = 0.1  # seconds

def parse_movie_nfo(nfo_file):
    """Parses the movie NFO to extract relevant collection and file information."""
    tree = ET.parse(nfo_file)
    root = tree.getroot()

    data = {}
    data['LocalTitle'] = root.findtext('title', default='Unknown Title')
    data['TmdbId'] = root.findtext('tmdbid', default='Unknown')
    
    # Extract collection set name and overview
    data['CollectionName'] = root.findtext('set/name', default=None)
    data['Overview'] = root.findtext('set/overview', default='No overview available.')

    data['OriginalFile'] = root.findtext('original_filename', default=None)

    # Extract genres and studios
    data['Genres'] = [genre.text for genre in root.findall('genre')]  # List of genres
    data['Studios'] = [studio.text for studio in root.findall('studio')]  # List of studios

    return data

def create_collection_xml(collection_name, collection_data, output_file, library_dir, collection_id=None, overwrite=False):
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
        
        # Format the path with single quotes if it contains spaces
        path = os.path.join(library_dir, movie['FullRelativePath'])
        ET.SubElement(collection_item, "Path").text = path

    # Add collection_id as a child element inside the XML, nested within the root Item
    if collection_id:
        ET.SubElement(root, "CollectionID").text = str(collection_id)

    # Pretty-print the XML
    xml_str = ET.tostring(root, encoding='utf-8')
    dom = minidom.parseString(xml_str)
    pretty_xml_as_string = dom.toprettyxml(indent="  ")

    # Check if the output file already exists and handle based on the overwrite flag
    if os.path.exists(output_file) and not overwrite:
        logging.info(f"Skipping existing XML for {collection_name}. Use --overwrite to force.")
        return  # Exit the function if the file exists and overwrite is False

    # Save the formatted XML string to a file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(pretty_xml_as_string)

    logging.info(f"Collection XML saved to {output_file}")


def fetch_collection_data_from_tmdb(tmdb_id, movie_data, api_key):
    """Fetches collection metadata from TMDb for a given collection."""
    if not api_key:
        logging.info("No TMDb API key provided. Skipping TMDb fetch.")
        return {'Overview': movie_data['Overview'], 'Genres': [], 'Studios': []}

    try:
        time.sleep(THROTTLE_TIME)  # Throttle API calls
        collection_info = requests.get(f"https://api.themoviedb.org/3/collection/{tmdb_id}?api_key={api_key}").json()
        
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

def find_video_file_for_nfo(nfo_file):
    """Finds the video file that corresponds to the given NFO file."""
    # Get the directory containing the NFO file
    nfo_dir = os.path.dirname(nfo_file)
    nfo_base = os.path.splitext(os.path.basename(nfo_file))[0]

    # Search for matching video files
    for ext in VIDEO_EXTENSIONS:
        video_file_path = os.path.join(nfo_dir, nfo_base + ext)
        if os.path.exists(video_file_path):
            return video_file_path
    return None

def download_and_extract_collection_ids():
    """Downloads and extracts the collection IDs from TMDb."""
    current_date = datetime.now().strftime("%m_%d_%Y")
    url = f"http://files.tmdb.org/p/exports/collection_ids_{current_date}.json.gz"
    
    try:
        logging.info(f"Downloading collection IDs from {url}")
        response = requests.get(url)
        response.raise_for_status()
        
        # Decompress the gzipped content
        json_data = gzip.decompress(response.content)
        
        # Decode the decompressed bytes into a string
        json_lines = json_data.decode('utf-8').splitlines()
        
        # Parse each line as a separate JSON object and build a dictionary
        collection_ids = {}
        for line in json_lines:
            try:
                entry = json.loads(line)
                collection_ids[entry['name']] = entry['id']
            except json.JSONDecodeError as e:
                logging.warning(f"Skipping invalid JSON line: {line} ({e})")
        
        return collection_ids
        
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        logging.error(f"Failed to download or parse collection IDs: {e}")
        return {}

def fetch_collection_images(collection_id, api_key, output_dir):
    """Fetch images for a specific collection using the TMDb API."""
    api_url = f"https://api.themoviedb.org/3/collection/{collection_id}/images?api_key={api_key}"
    try:
        response = requests.get(api_url)
        if response.status_code == 200:
            data = response.json()

            # Attempt to download the first English backdrop if available
            english_backdrops = [backdrop for backdrop in data.get('backdrops', []) if backdrop.get('iso_639_1') == 'en']
            if english_backdrops:
                backdrop_path = english_backdrops[0]['file_path']
                download_image(f"https://image.tmdb.org/t/p/original{backdrop_path}", os.path.join(output_dir, 'backdrop.jpg'))
            else:
                # Fall back to the first available backdrop
                if data.get('backdrops'):
                    backdrop_path = data['backdrops'][0]['file_path']
                    download_image(f"https://image.tmdb.org/t/p/original{backdrop_path}", os.path.join(output_dir, 'backdrop.jpg'))

            # Attempt to download the first English poster if available
            english_posters = [poster for poster in data.get('posters', []) if poster.get('iso_639_1') == 'en']
            if english_posters:
                poster_path = english_posters[0]['file_path']
                download_image(f"https://image.tmdb.org/t/p/original{poster_path}", os.path.join(output_dir, 'poster.jpg'))
            else:
                # Fall back to the first available poster
                if data.get('posters'):
                    poster_path = data['posters'][0]['file_path']
                    download_image(f"https://image.tmdb.org/t/p/original{poster_path}", os.path.join(output_dir, 'poster.jpg'))

        else:
            print(f"Failed to fetch images for collection ID {collection_id} (Status Code: {response.status_code})")
    except Exception as e:
        print(f"Error fetching images for collection ID {collection_id}: {e}")


def process_movie_nfo_files(library_dir, output_dir, api_key, overwrite=False):
    """Scans movie NFOs and builds collection XMLs based on the movie's collection information."""
    collections = {}

    # If the API key is provided, download the collection IDs
    collection_ids = {}
    if api_key:
        collection_ids = download_and_extract_collection_ids()

    # Traverse the NFO directory to find all NFO files
    for root, dirs, files in os.walk(library_dir):
        for file in files:
            if file.endswith('.nfo'):
                nfo_file_path = os.path.join(root, file)

                # Parse the movie NFO
                movie_data = parse_movie_nfo(nfo_file_path)

                # Check if the movie has a collection name
                if movie_data['CollectionName']:
                    # Clean up the collection name for folder naming
                    collection_name = f"{movie_data['CollectionName'].replace('/', ' - ')}"

                    # Find the video file that matches the NFO
                    video_file = find_video_file_for_nfo(nfo_file_path)

                    # Add movie info to the collections dictionary
                    if collection_name not in collections:
                        collections[collection_name] = {
                            'Movies': [],
                            'CollectionId': collection_ids.get(collection_name, None)
                        }
                    collections[collection_name]['Movies'].append({
                        'LocalTitle': movie_data['LocalTitle'],
                        'TmdbId': movie_data['TmdbId'],
                        'FullRelativePath': os.path.relpath(video_file, library_dir) if video_file else None,
                    })

    # Create collection XML files and download images for each collection
    for collection_name, collection_data in collections.items():
        output_file = os.path.join(output_dir, f"{collection_name}.xml")
        
        if os.path.exists(output_file) and not overwrite:
            logging.info(f"Skipping existing XML for {collection_name}. Use --overwrite to force.")
            continue

        # Fetch collection data from TMDb
        if collection_data['CollectionId']:
            tmdb_data = fetch_collection_data_from_tmdb(collection_data['CollectionId'], collection_data['Movies'][0], api_key)
            collection_data.update(tmdb_data)

            # Create XML for the collection
            create_collection_xml(collection_name, collection_data, output_file, library_dir, collection_data['CollectionId'])

            # Download collection images if API key is provided
            if api_key:
                fetch_collection_images(collection_data['CollectionId'], api_key, output_dir)
        else:
            logging.warning(f"No collection ID found for {collection_name}. Skipping.")

def download_image(url, file_path):
    """Downloads an image from the provided URL."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        with open(file_path, 'wb') as f:
            f.write(response.content)
        logging.info(f"Downloaded image to {file_path}")
    except Exception as e:
        logging.error(f"Failed to download image from {url}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate XML for movie collections and fetch images from TMDb.")
    parser.add_argument("--library_dir", required=True, help="Directory containing movie NFO files.")
    parser.add_argument('--output_dir', default='/var/lib/jellyfin/data/collections', help='Output directory for collection XMLs.')
    parser.add_argument("--key", default=None, help="TMDb API key (optional).")
    parser.add_argument("--overwrite", action='store_true', help="Overwrite existing XML files if they exist.")
    args = parser.parse_args()

    # Set up logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    process_movie_nfo_files(args.library_dir, args.output_dir, args.key, args.overwrite)
