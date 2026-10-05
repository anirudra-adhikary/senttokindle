import os
import shutil
import time
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv
from tqdm import tqdm

# ==========================================
# 1. LOAD PRIVATE CREDENTIALS FROM .env
# ==========================================
load_dotenv()

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
KINDLE_EMAIL = os.getenv("KINDLE_EMAIL")

# ==========================================
# 2. CONFIGURATION & SAFETY LIMITS
# ==========================================
SOURCE_FOLDER = "books-pdf"
SENT_FOLDER_NAME = "already_sent"
SKIPPED_FOLDER_NAME = "skipped"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB (Gmail SMTP attachment limit)
DELAY_BETWEEN_EMAILS = 180              # 3 minutes (prevents Gmail spam throttling)
MAX_EMAILS_PER_DAY = 100                # Keeps you below Google's 500/day hard limit

def check_credentials():
    """Verifies that all required secrets were loaded from the .env file."""
    if not all([SENDER_EMAIL, SENDER_PASSWORD, KINDLE_EMAIL]):
        print("[!] ERROR: Missing credentials!")
        print("[!] Please ensure your '.env' file exists and contains SENDER_EMAIL, SENDER_PASSWORD, and KINDLE_EMAIL.")
        return False
    return True

def send_pdf_to_kindle(file_path, file_name):
    """
    Constructs and sends the email preserving exact PDF layout.
    Raises an exception if SMTP delivery fails.
    """
    msg = EmailMessage()
    msg['From'] = SENDER_EMAIL
    msg['To'] = KINDLE_EMAIL
    
    # Subject left completely empty ("") to preserve exact fixed PDF layout on Kindle
    msg['Subject'] = ""

    with open(file_path, 'rb') as f:
        file_data = f.read()

    msg.add_attachment(
        file_data,
        maintype='application',
        subtype='octet-stream',
        filename=file_name
    )

    # Establish secure TLS connection and send
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)

def process_library():
    # 1. Validate credentials before doing anything
    if not check_credentials():
        return

    # 2. Setup checkpoint directory (books-pdf/already_sent)
    sent_dir = os.path.join(SOURCE_FOLDER, SENT_FOLDER_NAME)
    os.makedirs(sent_dir, exist_ok=True)
    
    #@anirudra
    skipped_dir = os.path.join(SOURCE_FOLDER, SKIPPED_FOLDER_NAME)
    os.makedirs(skipped_dir, exist_ok=True)
    

    # 3. Gather only unprocessed PDF files sitting in the root of SOURCE_FOLDER
    if not os.path.exists(SOURCE_FOLDER):
        print(f"[!] ERROR: Source folder '{SOURCE_FOLDER}' not found. Please create it and add your PDFs.")
        return

    files = [
        f for f in os.listdir(SOURCE_FOLDER) 
        if f.lower().endswith(('.pdf', '.epub')) and os.path.isfile(os.path.join(SOURCE_FOLDER, f))
    ]
    
    total_files = len(files)
    if total_files == 0:
        print(f"No new PDF files found in '{SOURCE_FOLDER}'. Everything is processed!")
        return

    print(f"Found {total_files} pending PDFs in '{SOURCE_FOLDER}'. Starting batch transfer...")
    sent_today = 0

    # 4. Main processing loop with MANUAL progress control
    # Using 'with' creates a clean progress bar that we control manually with pbar.update(1)
    with tqdm(total=total_files, desc="Uploading Library", unit="book", dynamic_ncols=True, colour="green") as pbar:
        
        for index, file_name in enumerate(files, 1):
            # Enforce daily safety cutoff
            if sent_today >= MAX_EMAILS_PER_DAY:
                tqdm.write(f"\n[!] Daily safety cap of {MAX_EMAILS_PER_DAY} reached.")
                tqdm.write("To protect your Gmail account quotas, stopping for today.")
                tqdm.write("Run the script again tomorrow to process the next batch!")
                break

            file_path = os.path.join(SOURCE_FOLDER, file_name)
            file_size = os.path.getsize(file_path)

            # Enforce file size limit
            if file_size > MAX_FILE_SIZE_BYTES:
                #segregate the skipped file in a different folder
                destination_path = os.path.join(skipped_dir, file_name)
                shutil.move(file_path, destination_path)
                size_mb = file_size / (1024 * 1024)
                tqdm.write(f"\n[{index}/{total_files}] SKIPPED: '{file_name}' ({size_mb:.2f} MB exceeds 25 MB limit)")
                tqdm.write(f"Moved to '{SKIPPED_FOLDER_NAME}'")
                pbar.update(1)  # Step the progress bar forward even for skipped files
                continue

            # Attempt sending and checkpointing
            try:
                pbar.set_description(f"Sending book {index}")
                tqdm.write(f"\n[{index}/{total_files}] Uploading: '{file_name}'...")
                send_pdf_to_kindle(file_path, file_name)
                
                # If we reached here, SMTP delivery succeeded. Move the file.
                destination_path = os.path.join(sent_dir, file_name)
                shutil.move(file_path, destination_path)
                sent_today += 1
                
                # INSTANTLY update the progress bar BEFORE sleeping!
                pbar.update(1)
                
                tqdm.write(f"--> Success! Verified and moved to '{SENT_FOLDER_NAME}'.")
                tqdm.write(f"--> Daily Progress: {sent_today}/{MAX_EMAILS_PER_DAY} files sent.")

                # Apply cool-off delay (only if there are more files left to send today)
                if sent_today < MAX_EMAILS_PER_DAY and index < total_files:
                    pbar.set_description("Cooling down (3 min)...")
                    tqdm.write(f"--> Pausing for {DELAY_BETWEEN_EMAILS} seconds to prevent rate-limiting...")
                    time.sleep(DELAY_BETWEEN_EMAILS)

            except (smtplib.SMTPException, ConnectionError, OSError) as e:
                tqdm.write(f"[!] Network or SMTP Error on '{file_name}': {e}")
                tqdm.write("[!] The file was NOT moved. It will be retried on your next run.")
                tqdm.write("[!] Pausing for 5 minutes before trying the next file...")
                pbar.set_description("Network Pause (5 min)...")
                time.sleep(300)
            except Exception as e:
                tqdm.write(f"[!] Unexpected error on '{file_name}': {e}")
                break

    print("\nBatch session complete.")

if __name__ == "__main__":
    process_library()