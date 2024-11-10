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

def create_collection_xml(collection_name, collection_data, output_file, library_dir, collection_id=None):
    """Creates a collection XML file with the gathered data."""
    root = ET.Element("Item")

    # Basic information about the collection
    ET.SubElement(root, "ContentRating").text = "NR"  # Placeholder for Content Rating
    ET.SubElement(root, "LockData").text = "false"
    ET.SubElement(root, "Overview").text = collection_data['Overview']
    ET.SubElement(root, "LocalTitle").text = collection_name
    ET.SubElement(root, "DisplayOrder").text = "PremiereDate"

    # Add the TmdbId instead of a comment
    if collection_id:
        ET.SubElement(root, "TmdbId").text = str(collection_id)

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

    # Pretty-print the XML
    xml_str = ET.tostring(root, encoding='utf-8')
    dom = minidom.parseString(xml_str)
    pretty_xml_as_string = dom.toprettyxml(indent="  ")

    # Save the formatted XML string to a file
    output_directory = os.path.dirname(output_file)
    os.makedirs(output_directory, exist_ok=True)  # Ensure the output directory exists
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(pretty_xml_as_string)

    logging.info(f"Collection XML saved to {output_file}")

def download_image(url, output_dir, name, overwrite=False):
    """Downloads an image from a URL and saves it to the specified directory."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    image_path = os.path.join(output_dir, name)

    # Check if the image exists and whether it should be overwritten
    if not os.path.exists(image_path) or overwrite:
        try:
            response = requests.get(url)
            response.raise_for_status()

            # Save the image with the appropriate name
            with open(image_path, 'wb') as img_file:
                img_file.write(response.content)
                logging.info(f"Downloaded image: {image_path}")

        except requests.exceptions.RequestException as e:
            logging.error(f"Error downloading image from {url}: {e}")
    else:
        logging.info(f"Image already exists, skipping download: {image_path}")

def fetch_collection_data_from_tmdb(tmdb_id, api_key):
    """Fetches collection metadata from TMDb for a given collection."""
    if not api_key:
        logging.info("No TMDb API key provided. Skipping TMDb fetch.")
        return {'Overview': 'No overview available.', 'Genres': [], 'Studios': [], 'Images': []}

    try:
        time.sleep(THROTTLE_TIME)  # Throttle API calls
        collection_info = requests.get(f"https://api.themoviedb.org/3/collection/{tmdb_id}?api_key={api_key}").json()
        
        if collection_info:
            # Prepare to download images
            images = []
            if 'backdrop_path' in collection_info:
                images.append((f"https://image.tmdb.org/t/p/original{collection_info['backdrop_path']}", "backdrop.jpg"))
            if 'poster_path' in collection_info:
                images.append((f"https://image.tmdb.org/t/p/original{collection_info['poster_path']}", "poster.jpg"))

            return {
                'Overview': collection_info.get('overview', 'No overview available.'),
                'Genres': [genre['name'] for genre in collection_info.get('genres', [])],
                'Studios': [studio['name'] for studio in collection_info.get('production_companies', [])],
                'Images': images
            }
        else:
            logging.warning(f"No collection data found for TMDb ID {tmdb_id}")
            return {'Overview': 'No overview available.', 'Genres': [], 'Studios': [], 'Images': []}
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching collection data from TMDb for ID {tmdb_id}: {e}")
        return {'Overview': 'No overview available.', 'Genres': [], 'Studios': [], 'Images': []}

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

                    if not video_file:
                        logging.warning(f"No matching video file found for NFO: {nfo_file_path}")
                        continue

                    # Use the full path relative to the library directory
                    movie_relative_path = os.path.relpath(video_file, library_dir)

                    # Add the movie to its collection
                    if collection_name not in collections:
                        collections[collection_name] = {
                            'Overview': movie_data['Overview'],
                            'Movies': [],
                            'Genres': [],
                            'Studios': []
                        }
                    collections[collection_name]['Movies'].append({
                        'Title': movie_data['LocalTitle'],
                        'FullRelativePath': movie_relative_path,
                    })

                    # Add genres and studios, ensuring no duplicates
                    collections[collection_name]['Genres'] = list(set(collections[collection_name]['Genres'] + movie_data['Genres']))
                    collections[collection_name]['Studios'] = list(set(collections[collection_name]['Studios'] + movie_data['Studios']))

    # Generate XML files for each collection
    for collection_name, collection_data in collections.items():
        collection_id = collection_ids.get(collection_name)  # Get the collection ID if available
        output_file_path = os.path.join(output_dir, collection_name, 'collection.xml')

        # Create the collection XML
        create_collection_xml(collection_name, collection_data, output_file_path, library_dir, collection_id)

        # Download collection images if any exist
        if collection_id:
            tmdb_data = fetch_collection_data_from_tmdb(collection_id, api_key)
            for img_url, img_name in tmdb_data['Images']:
                download_image(img_url, os.path.join(output_dir, collection_name), img_name, overwrite)

def main():
    parser = argparse.ArgumentParser(description="Create collection XML files from NFOs.")
    parser.add_argument("--library_dir", required=True, help="Directory containing NFO and video files.")
    parser.add_argument('--output_dir', default='/var/lib/jellyfin/data/collections', help='Output directory for collection XMLs.')
    parser.add_argument("--key", help="TMDb API key for fetching additional collection data.")
    parser.add_argument("--overwrite", action='store_true', help="Overwrite existing XML files.")

    args = parser.parse_args()

    # Set up logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Process the movie NFO files
    process_movie_nfo_files(args.library_dir, args.output_dir, args.key, args.overwrite)

if __name__ == "__main__":
    main()
