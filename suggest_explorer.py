import json
import time
import datetime
import urllib.parse
import requests
import csv
import os
import sys

# Google Sheets連携用のインポート
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

# Google サジェスト APIのベースURL
# client=chromeを指定するとJSON形式で結果が返ってくる
SUGGEST_URL = "http://google.com/complete/search?client=chrome&q={query}&hl={hl}&gl={gl}"

# 1. 初期シードキーワード (タイ語で「日本語学習」に関連する表現)
SEED_KEYWORDS = [
    "เรียนภาษาญี่ปุ่น",          # 日本語を学ぶ
    "ภาษาญี่ปุ่น",               # 日本語
    "ไวยากรณ์ภาษาญี่ปุ่น",       # 日本語文法
    "คำศัพท์ภาษาญี่ปุ่น",       # 日本語単語
    "เรียนญี่ปุ่น",              # 日本留学・学習
    "สอนภาษาญี่ปุ่น",            # 日本語を教える（教わる）
    "สนทนาภาษาญี่ปุ่น",          # 日本語会話
    "คอร์สภาษาญี่ปุ่น",          # 日本語コース
    "ภาษาญี่ปุ่นเบื้องต้น",      # 初級日本語
    "เรียนภาษาญี่ปุ่นด้วยตัวเอง", # 独学で日本語を学ぶ
    "สอบ JLPT",                 # JLPT受験
    "ข้อสอบภาษาญี่ปุ่น",         # 日本語の試験・過去問
]

# 2. 拡張用のサフィックス (タイ文字の主要な子音・母音およびアルファベット)
# タイ人がサジェストを絞り込む際に入力するであろう文字
SUFFIXES = [
    # タイ文字（代表的な子音・母音）
    "", "ก", "ข", "ค", "ง", "จ", "ช", "ด", "ต", "ท", "น", "บ", "ป", "ผ", "พ", "ฟ", "ม", "ย", "ร", "ล", "ว", "ส", "ห", "อ",
    "ะ", "า", "เ", "แ", "โ", "ใ", "ไ",
    # 英語アルファベット
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z"
]

def fetch_suggests(query, hl="th", gl="th"):
    """GoogleサジェストAPIからキーワードのリストを取得する"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    encoded_query = urllib.parse.quote(query)
    url = SUGGEST_URL.format(query=encoded_query, hl=hl, gl=gl)
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            # レスポンス形式: [query, [suggest1, suggest2, ...], [types, ...], ...]
            data = json.loads(response.text)
            if len(data) > 1:
                return data[1]
        else:
            print(f"[Warning] Failed to fetch suggest for '{query}': HTTP {response.status_code}")
    except Exception as e:
        print(f"[Error] Network error while fetching '{query}': {e}")
    return []

def collect_keywords():
    """シードキーワードとサフィックスを組み合わせてキーワードを徹底収集し、人気スコアを算出する"""
    keyword_scores = {} # {keyword: score}
    total_queries = len(SEED_KEYWORDS) * len(SUFFIXES)
    current_query_num = 0

    print(f"Starting keyword expansion with scoring...")
    print(f"Seed keywords: {len(SEED_KEYWORDS)}")
    print(f"Suffixes: {len(SUFFIXES)}")
    print(f"Total API requests planned: {total_queries}\n")

    for seed in SEED_KEYWORDS:
        print(f"Processing seed: '{seed}'")
        for suffix in SUFFIXES:
            current_query_num += 1
            query = f"{seed} {suffix}".strip()
            
            suggests = fetch_suggests(query)
            # サジェストの上位ほど検索頻度が高い傾向にあるため、順位に応じてスコアを付与
            # 1位: 10点, 2位: 9点, ... 10位以下: 1点
            for index, keyword in enumerate(suggests):
                rank_score = max(1, 10 - index)
                # すでに存在するキーワードの場合はスコアを累計（何度もサジェストされる語は重要度が高い）
                keyword_scores[keyword] = keyword_scores.get(keyword, 0) + rank_score
            
            if current_query_num % 50 == 0 or current_query_num == total_queries:
                print(f" Progress: {current_query_num}/{total_queries} queries completed. Unique keywords found: {len(keyword_scores)}")
            
            time.sleep(0.3)

    # スコアの高い順にソート
    sorted_keywords = sorted(keyword_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_keywords

def save_to_csv(scored_keywords, filepath="suggested_keywords.csv"):
    """結果をCSVファイルに保存する (日付、順位、キーワード、人気スコア)"""
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    try:
        # 新規作成または追記モード
        file_exists = os.path.exists(filepath)
        with open(filepath, "a" if file_exists else "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Date", "Rank", "Keyword", "Popularity Score"])
            
            # 上位100件を保存
            for rank, (kw, score) in enumerate(scored_keywords[:100], 1):
                writer.writerow([today_str, rank, kw, score])
        print(f"\n[Success] Saved top 100 keywords to '{filepath}'")
    except Exception as e:
        print(f"[Error] Failed to save CSV file: {e}")

def write_to_google_sheet(keywords, spreadsheet_name="Thai-Japanese Language Learning Keywords", credentials_path="credentials.json"):
    """Googleスプレッドシートに書き込む (Google Cloudサービスアカウント版)"""
    if not GSPREAD_AVAILABLE:
        print("\n[Skip] gspread or google-auth is not installed. Skipping Google Sheet upload.")
        return False
        
    if not os.path.exists(credentials_path):
        # サービスアカウントキーがない場合はスキップ（GAS URLのチェックへ移行するためにFalseを返す）
        return False

    print("\nConnecting to Google Sheets API using Service Account...")
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
        client = gspread.authorize(creds)

        try:
            sh = client.open(spreadsheet_name)
            print(f"Opened existing spreadsheet: '{spreadsheet_name}'")
        except gspread.exceptions.SpreadsheetNotFound:
            sh = client.create(spreadsheet_name)
            print(f"Created new spreadsheet: '{spreadsheet_name}'")
            
        worksheet = sh.get_worksheet(0)
        
        # シートをクリアしてヘッダーとデータを書き込み
        worksheet.clear()
        
        # データを[[kw1], [kw2], ...]の形式に変換
        data = [["Keyword"]] + [[kw] for kw in keywords]
        
        # 一括書き込み
        worksheet.update(range_name="A1", values=data)
        
        print(f"[Success] Successfully uploaded {len(keywords)} keywords to Google Sheet!")
        print(f"Spreadsheet URL: {sh.url}")
        print("💡 NOTE: If you created a new spreadsheet, make sure to share it with your personal Google account email to view it.")
        return True

    except Exception as e:
        print(f"[Error] Failed to write to Google Sheet: {e}")
        return False

def write_to_sheet_via_gas(scored_keywords, gas_url):
    """Google Apps Script (GAS) のウェブアプリURL経由でスプレッドシートに書き込む"""
    if not gas_url or gas_url.startswith("YOUR_"):
        print("\n[Info] GAS Web App URL is not set. Skipping GAS upload.")
        return False

    print("\nSending daily top 100 data to Google Sheets via GAS Web App...")
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    # 送信データ形式: [[Date, Rank, Keyword, Popularity Score], ...]
    data = []
    for rank, (kw, score) in enumerate(scored_keywords[:100], 1):
        data.append([today_str, rank, kw, score])
        
    try:
        response = requests.post(gas_url, json=data, timeout=30)
        if response.status_code == 200 and "Success" in response.text:
            print("[Success] Successfully uploaded daily top 100 keywords to Google Sheet via GAS!")
            return True
        else:
            print(f"[Error] GAS Upload failed. Response: {response.text} (Status: {response.status_code})")
    except Exception as e:
        print(f"[Error] Failed to connect to GAS: {e}")
    return False

def main():
    print("=== Google Suggest Keyword Collector for Thai Japanese Learners ===")
    
    # 環境変数または直接記述からGASのウェブアプリURLを取得
    GAS_WEBAPP_URL = os.environ.get("GAS_WEBAPP_URL", "https://script.google.com/macros/s/AKfycbyY2YXCgQWSNlqEmfXR5u7NHtQnPUKAgEFcw80_ZAqtO0JmH1LPJaaYWRHUVnoFUHlo/exec")
    
    # テストモードの確認
    if "--test" in sys.argv:
        print("[Test Mode] Running a quick test with 1 seed keyword and fewer suffixes...")
        global SEED_KEYWORDS, SUFFIXES
        SEED_KEYWORDS = [SEED_KEYWORDS[0]]
        SUFFIXES = ["", "ก", "a"]
    
    # キーワード収集の開始
    keywords = collect_keywords()
    
    # CSVへの保存
    save_to_csv(keywords)
    
    # GASへのアップロードを最優先 (GAS URLが有効な場合)
    uploaded = False
    if GAS_WEBAPP_URL and not GAS_WEBAPP_URL.startswith("YOUR_"):
        uploaded = write_to_sheet_via_gas(keywords, GAS_WEBAPP_URL)
    
    # GASが設定されていない、または失敗した場合のみ、サービスアカウント版を試行
    if not uploaded:
        write_to_google_sheet(keywords)
    
    print("\nProcess finished.")

if __name__ == "__main__":
    main()
