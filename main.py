import requests
import json
import time
import os
import multiprocessing
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, getcontext
import config

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Set decimal precision
getcontext().prec = 18

# Validate that all required environment variables are set
if not all([config.RPC_URL, config.RPC_USER, config.RPC_PASS]):
    raise ValueError("Missing required environment variables. Please check your .env file.")

class MempoolLimitError(Exception):
    pass

def rpc_call(method, params=[]):
    """Make an RPC call to the Evrmore node with retries."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": "script",
        "method": method,
        "params": params
    })
    for attempt in range(config.MAX_RETRIES):
        try:
            response = requests.post(config.RPC_URL, auth=(config.RPC_USER, config.RPC_PASS), data=payload)
            response.raise_for_status()
            response_json = response.json()
            if 'error' in response_json and response_json['error']:
                raise Exception(response_json['error'])
            return response_json['result']
        except (requests.exceptions.RequestException, Exception) as e:
            logger.error(f"RPC call failed (attempt {attempt + 1}/{config.MAX_RETRIES}): {e}")
            if attempt == config.MAX_RETRIES - 1:
                raise
            time.sleep(2 ** attempt)  # Exponential backoff

def get_satori_holders():
    """Retrieve a dictionary of addresses holding SATORI and their balances."""
    holders = {}
    try:
        result = rpc_call("listaddressesbyasset", [config.SATORI_ASSET_NAME])
        logger.info("Successfully retrieved asset holders.")
    except Exception as e:
        logger.error(f"Failed to retrieve asset holders: {e}")
        return holders

    if isinstance(result, dict):
        for address, balance in result.items():
            if balance > 0:
                holders[address] = Decimal(balance)
    return holders

def get_address_balance(address):
    """Get the balance of a specific address."""
    time.sleep(0.05)  # Rate limiting to avoid overwhelming the node
    try:
        balance_info = rpc_call("getaddressbalance", [{"addresses": [address]}])
        balance = Decimal(balance_info.get('balance', 0)) / Decimal('100000000')  # Convert satoshis to EVR
        return address, balance
    except Exception as e:
        logger.error(f"Failed to get balance for address {address}: {e}")
        return address, None

def send_airdrop(address, amount):
    """Send airdrop to a specific address."""
    try:
        txid = rpc_call("sendtoaddress", [address, str(amount)])
        logger.info(f"Successfully sent {amount} EVR to {address}. Transaction ID: {txid}")
        return address, True
    except Exception as e:
        if 'too-long-mempool-chain' in str(e):
            logger.warning(f"Encountered too-long-mempool-chain for {address}.")
            raise MempoolLimitError()
        else:
            logger.error(f"Failed to send {amount} EVR to {address}: {e}")
            return address, False

def process_batch(batch, retries=0):
    """Process a batch of airdrop transactions with retry logic for failed addresses."""
    successful_transactions = 0
    failed_transactions = 0
    total_evr_sent = Decimal('0')
    total_retries = 0
    transaction_times = []
    failed_addresses = batch.copy()

    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
        future_to_address = {executor.submit(send_airdrop, addr, config.TEST_AIRDROP_AMOUNT): addr for addr in failed_addresses}
        for future in as_completed(future_to_address):
            start_time = datetime.now()
            addr = future_to_address[future]
            try:
                addr, success = future.result()
                transaction_times.append(datetime.now() - start_time)
                if success:
                    successful_transactions += 1
                    total_evr_sent += config.TEST_AIRDROP_AMOUNT
                    failed_addresses.remove(addr)
                else:
                    failed_transactions += 1
            except MempoolLimitError:
                failed_transactions += len(failed_addresses)
                if retries < config.MAX_RETRIES:
                    logger.info(f"Retrying failed addresses due to mempool limit. Retry {retries + 1}/{config.MAX_RETRIES}")
                    time.sleep(config.TX_PROCESSING_PAUSE_TIME)
                    batch_success, batch_fail, batch_sent, batch_retries, batch_times = process_batch(failed_addresses, retries + 1)
                    successful_transactions += batch_success
                    failed_transactions += batch_fail
                    total_evr_sent += batch_sent
                    total_retries += batch_retries + 1
                    transaction_times.extend(batch_times)
                return successful_transactions, failed_transactions, total_evr_sent, total_retries, transaction_times

    return successful_transactions, failed_transactions, total_evr_sent, total_retries, transaction_times

def load_progress():
    """Load previously processed addresses from the progress file."""
    if os.path.exists(config.PROGRESS_FILE):
        with open(config.PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {"processed_addresses": []}

def save_progress(processed_addresses):
    """Save processed addresses to the progress file."""
    with open(config.PROGRESS_FILE, "w") as f:
        json.dump({"processed_addresses": processed_addresses}, f)

def main():
    """Main function to get SATORI holders and airdrop EVR."""
    start_time = datetime.now()
    logger.info("Fetching Satori holders...")
    satori_holders = get_satori_holders()
    logger.info(f"Found {len(satori_holders)} Satori holders")

    # Load progress to skip already processed addresses
    progress = load_progress()
    processed_addresses = set(progress["processed_addresses"])

    # Filter out addresses with existing balances
    addresses = list(satori_holders.keys())
    addresses_to_process = []

    for i in range(0, len(addresses), config.BALANCE_CHECK_BATCH_SIZE):
        batch = addresses[i:i + config.BALANCE_CHECK_BATCH_SIZE]
        logger.info(f"Processing balance check batch {i // config.BALANCE_CHECK_BATCH_SIZE + 1}/{(len(addresses) + config.BALANCE_CHECK_BATCH_SIZE - 1) // config.BALANCE_CHECK_BATCH_SIZE}")
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
            future_to_address = {executor.submit(get_address_balance, addr): addr for addr in batch}
            for future in as_completed(future_to_address):
                address, balance = future.result()
                if balance is not None:
                    logger.info(f"Address: {address}, Balance: {balance:.8f} EVR")
                    if balance <= Decimal('1.0') and address not in processed_addresses:
                        addresses_to_process.append(address)
                else:
                    logger.warning(f"Skipping address {address} as balance could not be retrieved")
        logger.info(f"Processed balance check batch {i // config.BALANCE_CHECK_BATCH_SIZE + 1}/{(len(addresses) + config.BALANCE_CHECK_BATCH_SIZE - 1) // config.BALANCE_CHECK_BATCH_SIZE}")
        time.sleep(config.BALANCE_CHECK_PAUSE_TIME)

    logger.info(f"Total addresses to process: {len(addresses_to_process)}")

    total_addresses = len(addresses_to_process)
    successful_transactions = 0
    failed_transactions = 0
    total_evr_sent = Decimal('0')
    total_retries = 0
    transaction_times = []

    for i in range(0, total_addresses, config.TX_PROCESSING_BATCH_SIZE):
        batch = addresses_to_process[i:i + config.TX_PROCESSING_BATCH_SIZE]
        logger.info(f"Processing airdrop batch {i // config.TX_PROCESSING_BATCH_SIZE + 1}/{(total_addresses + config.TX_PROCESSING_BATCH_SIZE - 1) // config.TX_PROCESSING_BATCH_SIZE}")
        batch_successful, batch_failed, batch_sent, batch_retries, batch_times = process_batch(batch)
        successful_transactions += batch_successful
        failed_transactions += batch_failed
        total_evr_sent += batch_sent
        total_retries += batch_retries
        transaction_times.extend(batch_times)
        # Update processed addresses
        processed_addresses.update(batch)
        save_progress(list(processed_addresses))
        logger.info(f"Processed airdrop batch {i // config.TX_PROCESSING_BATCH_SIZE + 1}/{(total_addresses + config.TX_PROCESSING_BATCH_SIZE - 1) // config.TX_PROCESSING_BATCH_SIZE}")
        time.sleep(config.TX_PROCESSING_PAUSE_TIME)

    if transaction_times:
        average_transaction_time = sum(transaction_times, timedelta()) / len(transaction_times)
    else:
        average_transaction_time = timedelta()

    end_time = datetime.now()
    total_time = end_time - start_time

    logger.info("\nAirdrop completed.")
    logger.info("\nSummary Report:")
    logger.info(f"Total number of addresses processed: {total_addresses}")
    logger.info(f"Total number of successful transactions: {successful_transactions}")
    logger.info(f"Total number of failed transactions: {failed_transactions}")
    logger.info(f"Total amount of EVR sent: {total_evr_sent:.8f} EVR")
    logger.info(f"Total number of retries: {total_retries}")
    logger.info(f"Average time per transaction: {average_transaction_time}")
    logger.info(f"Total time taken: {total_time}")

if __name__ == "__main__":
    # Dynamically set MAX_WORKERS based on CPU count, capped by config
    config.MAX_WORKERS = min(config.MAX_WORKERS, multiprocessing.cpu_count() * 2)
    main()
