import requests
import json
import time
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, getcontext

# Load environment variables from .env file
load_dotenv()

# Set decimal precision
getcontext().prec = 18

# Evrmore node RPC details
RPC_URL = os.getenv("RPC_URL")
RPC_USER = os.getenv("RPC_USER")
RPC_PASS = os.getenv("RPC_PASS")

# Validate that all required environment variables are set
if not all([RPC_URL, RPC_USER, RPC_PASS]):
    raise ValueError("Missing required environment variables. Please check your .env file.")

SATORI_ASSET_NAME = "SATORI"  # Replace with the exact asset name
TEST_AIRDROP_AMOUNT = Decimal('0.001')  # Amount to airdrop in EVR for testing
BALANCE_CHECK_BATCH_SIZE = 10000  # Number of addresses to process in one balance check batch
TX_PROCESSING_BATCH_SIZE = 300  # Number of addresses to process in one transaction batch
BALANCE_CHECK_PAUSE_TIME = 30  # Pause time between balance check batches in seconds
TX_PROCESSING_PAUSE_TIME = 120  # Pause time between transaction processing batches in seconds
MAX_WORKERS = 40  # Number of concurrent threads for balance checks and airdrop processing
MAX_RETRIES = 5  # Maximum number of retries for airdrop

class MempoolLimitError(Exception):
    pass

def rpc_call(method, params=[]):
    """Make an RPC call to the Evrmore node."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": "script",
        "method": method,
        "params": params
    })
    try:
        response = requests.post(RPC_URL, auth=(RPC_USER, RPC_PASS), data=payload)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e}")
        print(f"Response content: {response.content}")
        raise
    except requests.exceptions.RequestException as e:
        print(f"Request Exception: {e}")
        raise

    response_json = response.json()
    if 'error' in response_json and response_json['error']:
        print(f"RPC Error: {response_json['error']}")
        raise Exception(response_json['error'])
    
    return response_json['result']

def get_satori_holders():
    """Retrieve a dictionary of addresses holding SATORI and their balances."""
    holders = {}
    
    try:
        result = rpc_call("listaddressesbyasset", [SATORI_ASSET_NAME])
        print("Successfully retrieved asset holders.")
    except Exception as e:
        print(f"Failed to retrieve asset holders: {e}")
        return holders

    if isinstance(result, dict):
        for address, balance in result.items():
            if balance > 0:
                holders[address] = Decimal(balance)

    return holders

def get_address_balance(address):
    """Get the balance of a specific address."""
    try:
        balance_info = rpc_call("getaddressbalance", [{"addresses": [address]}])
        balance = Decimal(balance_info.get('balance', 0)) / Decimal('100000000')  # Convert satoshis to EVR
        return address, balance
    except Exception as e:
        print(f"Failed to get balance for address {address}: {e}")
        return address, None

def send_airdrop(address, amount):
    """Send airdrop to a specific address."""
    try:
        txid = rpc_call("sendtoaddress", [address, str(amount)])
        print(f"Successfully sent {amount} EVR to {address}. Transaction ID: {txid}")
        return address, True
    except Exception as e:
        if 'too-long-mempool-chain' in str(e):
            print(f"Encountered too-long-mempool-chain for {address}.")
            raise MempoolLimitError()
        else:
            print(f"Failed to send {amount} EVR to {address}: {e}")
            return address, False

def process_batch(batch, retries=0):
    successful_transactions = 0
    failed_transactions = 0
    total_evr_sent = Decimal('0')
    total_retries = 0
    transaction_times = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_address = {executor.submit(send_airdrop, address, TEST_AIRDROP_AMOUNT): address for address in batch}
        for future in as_completed(future_to_address):
            transaction_start_time = datetime.now()
            address = future_to_address[future]
            try:
                address, success = future.result()
                transaction_end_time = datetime.now()
                transaction_times.append(transaction_end_time - transaction_start_time)
                if success:
                    successful_transactions += 1
                    total_evr_sent += TEST_AIRDROP_AMOUNT
                else:
                    failed_transactions += 1
            except MempoolLimitError:
                if retries < MAX_RETRIES:
                    print(f"Retrying batch due to too-long-mempool-chain error. Retry {retries + 1}/{MAX_RETRIES}")
                    time.sleep(TX_PROCESSING_PAUSE_TIME)
                    batch_successful, batch_failed, batch_sent, batch_retries, batch_times = process_batch(batch, retries + 1)
                    successful_transactions += batch_successful
                    failed_transactions += batch_failed
                    total_evr_sent += batch_sent
                    total_retries += batch_retries + 1
                    transaction_times.extend(batch_times)
                else:
                    print(f"Failed to process batch after {MAX_RETRIES} retries due to too-long-mempool-chain.")
                    failed_transactions += len(batch)

    return successful_transactions, failed_transactions, total_evr_sent, total_retries, transaction_times

def main():
    """Main function to get SATORI holders and airdrop EVR."""
    start_time = datetime.now()
    print("Fetching Satori holders...")
    satori_holders = get_satori_holders()
    print(f"Found {len(satori_holders)} Satori holders")

    # Filter out addresses with existing balances
    addresses = list(satori_holders.keys())
    addresses_to_process = []

    for i in range(0, len(addresses), BALANCE_CHECK_BATCH_SIZE):
        batch = addresses[i:i+BALANCE_CHECK_BATCH_SIZE]
        print(f"Processing balance check batch {i // BALANCE_CHECK_BATCH_SIZE + 1}/{(len(addresses) + BALANCE_CHECK_BATCH_SIZE - 1) // BALANCE_CHECK_BATCH_SIZE}")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_address = {executor.submit(get_address_balance, address): address for address in batch}
            for future in as_completed(future_to_address):
                address, balance = future.result()
                if balance is not None:
                    print(f"Address: {address}, Balance: {balance:.8f} EVR")
                    if balance <= Decimal('1.0'):
                        addresses_to_process.append(address)
                else:
                    print(f"Skipping address {address} as balance could not be retrieved")
        print(f"Processed balance check batch {i // BALANCE_CHECK_BATCH_SIZE + 1}/{(len(addresses) + BALANCE_CHECK_BATCH_SIZE - 1) // BALANCE_CHECK_BATCH_SIZE}")
        time.sleep(BALANCE_CHECK_PAUSE_TIME)

    print(f"Total addresses to process: {len(addresses_to_process)}")

    total_addresses = len(addresses_to_process)
    successful_transactions = 0
    failed_transactions = 0
    total_evr_sent = Decimal('0')
    total_retries = 0
    transaction_times = []

    for i in range(0, total_addresses, TX_PROCESSING_BATCH_SIZE):
        batch = addresses_to_process[i:i+TX_PROCESSING_BATCH_SIZE]
        print(f"Processing airdrop batch {i // TX_PROCESSING_BATCH_SIZE + 1}/{(total_addresses + TX_PROCESSING_BATCH_SIZE - 1) // TX_PROCESSING_BATCH_SIZE}")
        batch_successful, batch_failed, batch_sent, batch_retries, batch_times = process_batch(batch)
        successful_transactions += batch_successful
        failed_transactions += batch_failed
        total_evr_sent += batch_sent
        total_retries += batch_retries
        transaction_times.extend(batch_times)
        print(f"Processed airdrop batch {i // TX_PROCESSING_BATCH_SIZE + 1}/{(total_addresses + TX_PROCESSING_BATCH_SIZE - 1) // TX_PROCESSING_BATCH_SIZE}")
        time.sleep(TX_PROCESSING_PAUSE_TIME)

    if transaction_times:
        average_transaction_time = sum(transaction_times, timedelta()) / len(transaction_times)
    else:
        average_transaction_time = timedelta()

    end_time = datetime.now()
    total_time = end_time - start_time

    print("\nAirdrop completed.")
    print("\nSummary Report:")
    print(f"Total number of addresses processed: {total_addresses}")
    print(f"Total number of successful transactions: {successful_transactions}")
    print(f"Total number of failed transactions: {failed_transactions}")
    print(f"Total amount of EVR sent: {total_evr_sent:.8f} EVR")
    print(f"Total number of retries: {total_retries}")
    print(f"Average time per transaction: {average_transaction_time}")
    print(f"Total time taken: {total_time}")

if __name__ == "__main__":
    main()
