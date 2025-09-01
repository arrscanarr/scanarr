#!/usr/bin/env python3
"""
Tracker Search Script

This script searches for files and folders against a tracker API and reports
which ones are not found on the tracker.
"""

import os
import sys
import argparse
import requests
import bencodepy
import time
from urllib.parse import quote_plus
from typing import List, Dict, Any
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


class TrackerSearcher:
    def __init__(self, api_url: str, api_key: str, tracker: str, delay: float = 0, max_retries: int = 10):
        """
        Initialize the tracker searcher.

        Args:
            api_url: Base URL of the tracker API
            api_key: API key for authentication
            tracker: Tracker name/ID to search
            delay: Delay in seconds between requests (default: 0)
        """
        self.api_url = api_url
        self.api_key = api_key
        self.tracker = tracker
        self.delay = delay
        self.max_retries = max_retries
        self.session = requests.Session()

    def search_tracker(self, query: str) -> List[Dict] | None:
        """
        Search the tracker API for a given query.

        Args:
            query: Search query string

        Returns:
            List of search results from the API
        """
        encoded_query = quote_plus(query)
        encoded_tracker = quote_plus(self.tracker)

        url = f"{self.api_url}/api/v2.0/indexers/all/results"
        params = {
            'apikey': self.api_key,
            'Query': encoded_query,
            'Tracker[]': encoded_tracker
        }

        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        json_response = response.json()

        # Check for errors in the indexers
        indexers = json_response.get('Indexers', [])
        for indexer in indexers:
            error = indexer.get('Error')
            if error:
                if "TooManyRequests" in error:
                    console.print(f"[bold red]Error:[/bold red] Too many requests for query '{query}'.")
                else:
                    console.print(f"[bold red]Error:[/bold red] Unknown error occurred for query '{query}'. Check Jackett logs for more details.")

                return None
        return json_response.get('Results', [])

    def get_torrent_name(self, torrent_url: str) -> str:
        """
        Download a torrent file and extract its top-level name.

        Args:
            torrent_url: URL to the torrent file

        Returns:
            Top-level name from the torrent file, or empty string if failed
        """
        # Apply delay before downloading torrent
        # if self.delay > 0:
        #    time.sleep(self.delay)

        try:
            response = self.session.get(torrent_url, timeout=30)
            response.raise_for_status()

            # Parse the torrent file
            torrent_data = bencodepy.decode(response.content)

            # Get the name from the info section
            if b'info' in torrent_data and b'name' in torrent_data[b'info']:
                name = torrent_data[b'info'][b'name'].decode('utf-8')
                return name

        except Exception as e:
            console.print(f"[bold red]Error[/bold red] parsing torrent from {torrent_url}: {e}")

        return ""

    def matches_query(self, torrent_name: str, query: str) -> bool:
        """
        Check if the torrent name matches the search query.

        Args:
            torrent_name: Name extracted from torrent file
            query: Original search query

        Returns:
            True if they match (case-insensitive), False otherwise
        """
        # Simple case-insensitive matching
        # You might want to make this more sophisticated based on your needs
        return query.lower() in torrent_name.lower()

    def search_and_verify_all(self, query_items: List[str], verbose: bool = False) -> List[str]:
        found = []

        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True
        ) as progress:
            task = progress.add_task("Searching...", total=len(query_items))

            for i, item in enumerate(query_items, 1):
                if i > 1 and self.delay > 0:
                    time.sleep(self.delay)

                # Update the progress description
                progress.update(task, description=f"Searching [{i}/{len(query_items)}] {item[:50]}...")

                # Perform the search
                if self.search_and_verify(item, verbose=verbose):
                    found.append(item)

                # Update progress
                progress.update(task, advance=1)

        return found

    def search_and_verify(self, query: str, verbose: bool = False) -> bool:
        """
        Search for a query and verify if it exists on the tracker.

        Args:
            query: Search query string
            verbose: Whether to show detailed output

        Returns:
            True if found on tracker, False otherwise
        """

        raw_results = None
        had_errors = False

        for attempt in range(self.max_retries):
            raw_results = self.search_tracker(query)
            if raw_results is not None:
                break
            else:
                had_errors = True
                retry_delay = max(self.delay, 4.0) * (attempt + 1)
                console.print(f"[yellow]Warning:[/yellow] Search failed. Retrying in {retry_delay}s (Attempt {attempt + 1} of {self.max_retries})")
                time.sleep(retry_delay)

        if raw_results is None:
            console.print("[bold red]Error:[/bold red] Search failed! No more retries left.")
            console.print("Depending on the cause of the error, you may want to increase the delay between requests or check your credentials / IP bans.")
            sys.exit(1)

        if len(raw_results) > 5:
            console.print(f"[bold red]Error:[/bold red] Too many results ({len(raw_results)}) for query '{query}'. Aborting.")
            sys.exit(1)

        if had_errors:
            self.delay += 1
            console.print("[yellow]Warning:[/yellow] Because there were errors during this search, the global delay has been increased by 1s. Please consider raising it by default.")

        results = []
        found_match = False

        for result in raw_results:
            original_title = result.get('Title')
            link = result.get('Link')

            results.append(original_title)

            torrent_name = self.get_torrent_name(link)
            if torrent_name and self.matches_query(torrent_name, query):
                found_match = True

        # Show detailed output only in verbose mode
        if verbose:
            # List all results with their titles
            console.print(f"[bold]Search results for:[/bold] {query}")

            results_amount = len(results)
            if results_amount > 0:
                if found_match:
                    console.print("[green]✓[/green] Found matching result")
                else:
                    console.print("[red]✗[/red] No match found in results")

                console.print(f"  Found {results_amount} results:")
                for result in results:
                    console.print(f"    {result}")
            else:
                console.print("[red]✗[/red] No results found")
            console.print()

        return found_match


def get_files_and_folders(directory: str) -> List[str]:
    """
    Get all files and folders in the specified directory.

    Args:
        directory: Path to the directory to scan

    Returns:
        List of file and folder names (not full paths)
    """
    try:
        items = []
        for item in os.listdir(directory):
            items.append(item)
        return items
    except OSError as e:
        console.print(f"[bold red]Error[/bold red] reading directory '{directory}': {e}")
        sys.exit(1)


def extract_group_name(filename: str) -> str:
    """
    Extract the group name from a filename.
    Group name is everything after the last dash.

    Args:
        filename: The filename to extract group name from

    Returns:
        Group name if found, empty string otherwise
    """
    if '-' in filename:
        return filename.split('-')[-1]
    return ""


def filter_items_by_group(items: List[str], excluded_groups: List[str]) -> tuple[List[str], int]:
    """
    Filter out items that belong to excluded groups.

    Args:
        items: List of file/folder names
        excluded_groups: List of group names to exclude

    Returns:
        Tuple of (filtered_items, number_of_skipped_items)
    """
    if not excluded_groups:
        return items, 0

    filtered_items = []
    skipped_count = 0

    for item in items:
        group_name = extract_group_name(item)
        if group_name in excluded_groups:
            skipped_count += 1
        else:
            filtered_items.append(item)

    return filtered_items, skipped_count


def has_sample_files(folder_path: str) -> bool:
    """
    Check if a folder contains media files between 1MB and 110MB (potential samples).
    Recursively checks all subfolders. Only checks common media file types.

    Args:
        folder_path: Path to the folder to check

    Returns:
        True if folder contains media files between 1MB and 110MB, False otherwise
    """
    min_size = 1 * 1024 * 1024  # 1MB in bytes
    max_size = 110 * 1024 * 1024  # 110MB in bytes

    # Common media file extensions
    media_extensions = {
        '.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v',
        '.mpg', '.mpeg', '.3gp', '.asf', '.rm', '.rmvb', '.ts', '.m2ts',
        '.mts', '.vob', '.ogv', '.divx', '.xvid'
    }

    try:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                # Check if file has a media extension
                file_ext = os.path.splitext(file)[1].lower()
                if file_ext not in media_extensions:
                    continue

                file_path = os.path.join(root, file)
                try:
                    file_size = os.path.getsize(file_path)
                    if min_size <= file_size <= max_size:
                        return True
                except OSError:
                    # Skip files that can't be accessed
                    continue
    except OSError as e:
        console.print(f"[yellow]Warning:[/yellow] Error checking folder '{folder_path}': {e}")

    return False


def has_proof_images(folder_path: str) -> bool:
    """
    Check if a folder contains image files with "proof" in their filename.
    Recursively checks all subfolders. Only checks common image file types.

    Args:
        folder_path: Path to the folder to check

    Returns:
        True if folder contains image files with "proof" in filename, False otherwise
    """
    # Common image file extensions
    image_extensions = {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp',
        '.svg', '.ico', '.psd', '.raw', '.cr2', '.nef', '.arw', '.dng'
    }

    try:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                # Check if file has an image extension
                file_ext = os.path.splitext(file)[1].lower()
                if file_ext not in image_extensions:
                    continue

                # Check if filename contains "proof" (case-insensitive)
                if 'proof' in file.lower():
                    return True
    except OSError as e:
        console.print(f"[yellow]Warning:[/yellow] Error checking folder '{folder_path}' for proofs: {e}")

    return False


def get_sample_indicators(items: List[str], base_directory: str) -> Dict[str, bool]:
    """
    Check which items contain sample files.

    Args:
        items: List of item names
        base_directory: Base directory path to resolve item paths

    Returns:
        Dictionary mapping item names to boolean indicating if they contain samples
    """
    result = {}

    for item in items:
        item_path = os.path.join(base_directory, item)

        # Only check folders
        if os.path.isdir(item_path):
            result[item] = has_sample_files(item_path)
        else:
            result[item] = False

    return result


def get_proof_indicators(items: List[str], base_directory: str) -> Dict[str, bool]:
    """
    Check which items contain proof images.

    Args:
        items: List of item names
        base_directory: Base directory path to resolve item paths

    Returns:
        Dictionary mapping item names to boolean indicating if they contain proof images
    """
    result = {}

    for item in items:
        item_path = os.path.join(base_directory, item)

        # Only check folders
        if os.path.isdir(item_path):
            result[item] = has_proof_images(item_path)
        else:
            result[item] = False

    return result


def get_labelled_items(items: List[str], base_directory: str) -> List[Dict[str, Any]]:
    """
    Get items with all their labels and indicators.

    Args:
        items: List of item names
        base_directory: Base directory path to resolve item paths

    Returns:
        List of dictionaries containing item info and labels
    """
    # Get all indicators
    sample_indicators = get_sample_indicators(items, base_directory)
    proof_indicators = get_proof_indicators(items, base_directory)

    result = []

    for item in items:
        item_path = os.path.join(base_directory, item)

        item_info = {
            'name': item,
            'original_name': item,
            'is_folder': os.path.isdir(item_path),
            'labels': {
                'has_samples': sample_indicators.get(item, False),
                'has_proof': proof_indicators.get(item, False)
            }
        }

        # Build label string
        labels = []
        if item_info['labels']['has_samples']:
            labels.append('S')
        if item_info['labels']['has_proof']:
            labels.append('P')

        # Add labels to display name
        if labels:
            label_string = '(' + ''.join(labels) + ')'
            item_info['name'] = f"{label_string} {item}"

        result.append(item_info)

    return result


def main():
    parser = argparse.ArgumentParser(description='Search tracker for files and folders')
    parser.add_argument('input_dir', help='Input directory to scan')
    parser.add_argument('--api-url', default='http://127.0.0.1:9117',
                        help='Tracker API base URL (default: http://127.0.0.1:9117)')
    parser.add_argument('--api-key', required=True, help='API key for the tracker')
    parser.add_argument('--tracker', required=True, help='Tracker name/ID to search')
    parser.add_argument('--exclude-groups', nargs='+', default=[],
                        help='Group names to exclude from search (group name is after last dash in filename)')
    parser.add_argument('--delay', type=float, default=0,
                        help='Delay in seconds between requests (default: 0, recommended: 1-3 seconds for rate limiting)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed search results (default: show minimal progress)')

    args = parser.parse_args()

    if not os.path.isdir(args.input_dir):
        console.print(f"[bold red]Error:[/bold red] '{args.input_dir}' is not a valid directory")
        sys.exit(1)

    # Initialize the searcher
    searcher = TrackerSearcher(args.api_url, args.api_key, args.tracker, args.delay)

    # Print delay information if enabled
    if args.delay > 0:
        console.print(f"Using delay of {args.delay} seconds between requests")

    # Get all files and folders
    console.print(f"[bold]Scanning directory:[/bold] {args.input_dir}")
    all_items = get_files_and_folders(args.input_dir)
    console.print(f"Found {len(all_items)} items total")

    # Filter out excluded groups
    items, skipped_count = filter_items_by_group(all_items, args.exclude_groups)

    if args.exclude_groups:
        console.print(f"[bold]Excluded groups:[/bold] {', '.join(args.exclude_groups)}")
        console.print(f"Skipped {skipped_count} items due to group filtering")

    console.print(f"[bold]Items to search:[/bold] {len(items)}")
    console.print()

    # Search for each item
    not_found = [item for item in items if item not in searcher.search_and_verify_all(items, args.verbose)]

    # Print results
    console.print("\n" + "=" * 50)
    console.print("[bold]RESULTS[/bold]")
    console.print("=" * 50)

    if not_found:
        # Add sample indicators to items that may contain samples
        console.print("Checking for potential sample files and proof images in folders...")
        labelled_items = get_labelled_items(not_found, args.input_dir)

        # Calculate the maximum label width for proper alignment
        max_label_width = 0
        for item_info in labelled_items:
            labels = []
            if item_info['labels']['has_samples']:
                labels.append('S')
            if item_info['labels']['has_proof']:
                labels.append('P')

            if labels:
                label_width = len('(' + ''.join(labels) + ')')
                max_label_width = max(max_label_width, label_width)

        console.print(f"\n[bold]Files/folders NOT found on tracker ({len(labelled_items)}):[/bold]")
        for item_info in labelled_items:
            labels = []
            if item_info['labels']['has_samples']:
                labels.append('S')
            if item_info['labels']['has_proof']:
                labels.append('P')

            if labels:
                label_string = '(' + ''.join(labels) + ')'
                # Pad label to max width
                formatted_label = label_string.ljust(max_label_width)
                console.print(f"  [yellow]{formatted_label}[/yellow] {item_info['original_name']}")
            else:
                # Add spaces to align with labeled items
                padding = ' ' * (max_label_width + 1) if max_label_width > 0 else ''
                console.print(f"  {padding}{item_info['original_name']}")

        # Print legend if any items have flags
        has_samples = any(item['labels']['has_samples'] for item in labelled_items)
        has_proof = any(item['labels']['has_proof'] for item in labelled_items)

        if has_samples or has_proof:
            console.print("\n[bold]Legend:[/bold]")
            if has_samples:
                console.print("  [yellow]S[/yellow] = Folder may contain sample files (media files 1MB-110MB)")
            if has_proof:
                console.print("  [yellow]P[/yellow] = Folder may contain proof images (image files with 'proof' in filename)")
    else:
        console.print("\n[green]All files/folders were found on the tracker![/green]")

    console.print(f"\n[bold]Total items found:[/bold] {len(all_items)}")
    if skipped_count > 0:
        console.print(f"[bold]Items skipped due to group filtering:[/bold] {skipped_count}")
    console.print(f"[bold]Items checked:[/bold] {len(items)}")
    console.print(f"[bold green]Items found on tracker:[/bold green] {len(items) - len(not_found)}")
    console.print(f"[bold red]Items NOT found on tracker:[/bold red] {len(not_found)}")


if __name__ == "__main__":
    main()
