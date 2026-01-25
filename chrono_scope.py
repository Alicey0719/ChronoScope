import ntplib
import os
import json
import time
import requests
import statistics
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any, Union

# --- 環境変数の読み込み ---
EXTERNAL_SOURCES: List[str] = json.loads(os.getenv("EXTERNAL_SOURCES", '["ntp.nict.jp", "time.google.com", "pool.ntp.org"]'))
LOCAL_SERVERS: List[Dict[str, Any]] = json.loads(os.getenv("LOCAL_SERVERS", '[]'))
DRIFT_THRESHOLD: float = float(os.getenv("DRIFT_THRESHOLD", "1.0"))
NOTIFY_METHOD: str = os.getenv("NOTIFY_METHOD", "discord").lower()
DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")
CHECK_INTERVAL: int = int(os.getenv("CHECK_INTERVAL", "60"))

class Notifier:
    @staticmethod
    def send(title: str, content: str, color: int = 16711680) -> None:
        """アラート通知（赤色）"""
        clean_content = content.replace('\n', ' ')
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [ALERT] {title}: {clean_content}")
        
        if NOTIFY_METHOD == "discord":
            Notifier.discord(title, content, color)

    @staticmethod
    def log(message: str) -> None:
        """正常時のログ出力"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO] {message}")

    @staticmethod
    def discord(title: str, content: str, color: int) -> None:
        if not DISCORD_WEBHOOK_URL: return
        payload = {"embeds": [{"title": title, "description": content, "color": color, "timestamp": datetime.now(timezone.utc).isoformat()}]}
        try: requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        except Exception as e: print(f"Notification error: {e}")

def get_ntp_info(host: str) -> Optional[ntplib.NTPStats]:
    client = ntplib.NTPClient()
    try: return client.request(host, version=4, timeout=2)
    except: return None

def monitor() -> None:
    Notifier.log(f"--- NTP Monitor Started (Interval: {CHECK_INTERVAL}s / Threshold: {DRIFT_THRESHOLD}s / Notify: {NOTIFY_METHOD} ) ---")
    Notifier.log(f"External Sources: {EXTERNAL_SOURCES}")
    Notifier.log(f"Local Servers: {[item['host'] for item in LOCAL_SERVERS]}")
    Notifier.log("------------------------------------------------------------")
    
    while True:
        # 1. 外部ソースから基準値（Baseline）を算出
        external_offsets: List[float] = []
        for host in EXTERNAL_SOURCES:
            res = get_ntp_info(host)
            if res: 
                Notifier.log(f"  External Source OK [{host}] Offset: {res.offset:.5f}s")
                external_offsets.append(res.offset)
        
        if len(external_offsets) < 2:
            Notifier.log("Warning: Not enough external sources for baseline.")
            time.sleep(CHECK_INTERVAL)
            continue

        baseline_offset = statistics.median(external_offsets)
        global_issues_found = False

        # 2. 監視対象のチェック
        for item in LOCAL_SERVERS:
            host: str = item.get("host", "unknown")
            res = get_ntp_info(host)
            server_issue_found = False
            
            if not res:
                Notifier.send("🚫 疎通エラー", f"サーバ: {host}\nNTPリクエストに応答がありません。")
                global_issues_found = True
                continue

            true_drift = abs(res.offset - baseline_offset)
            dt = datetime.fromtimestamp(res.tx_time)
            
            # --- チェック処理 ---
            
            # A. 2038年問題/異常時刻
            if dt.year < 2026:
                Notifier.send("🚨 緊急: 過去への巻き戻り", f"サーバ: {host}\n時刻: {dt}\nオーバーフローまたはリセットが発生した可能性があります。")
                server_issue_found = True

            # B. 時刻ズレ
            elif true_drift > DRIFT_THRESHOLD:
                Notifier.send("🕒 時刻ズレ検知", f"サーバ: {host}\n基準との差: {true_drift:.4f}s")
                server_issue_found = True

            # C. Stratum
            expected_stratum = item.get("expected_stratum")
            if expected_stratum is not None and res.stratum != expected_stratum:
                Notifier.send("📉 Stratum異常", f"サーバ: {host}\n現在: {res.stratum} (期待値: {expected_stratum})")
                server_issue_found = True
            
            # D. RefID (ソース)
            refid_str = ntplib.ref_id_to_text(res.ref_id, res.stratum)
            expected_refid = item.get("expected_refid")
            
            if expected_refid:
                valid_refs = [expected_refid] if isinstance(expected_refid, str) else expected_refid
                if not any(ref in refid_str for ref in valid_refs):
                    Notifier.send("📡 ソース異常", f"サーバ: {host}\n現在: {refid_str}\n期待値: {valid_refs}")
                    server_issue_found = True

            # このサーバに異常がないとき
            if not server_issue_found:
                Notifier.log(f"  OK [{host}] Offset: {true_drift:.5f}s | DT: {dt.strftime('%Y-%m-%d %H:%M:%S')} | St: {res.stratum} | Ref: {refid_str}")
            else:
                global_issues_found = True

        # 全体サマリ
        if not global_issues_found:
            Notifier.log(f"Check complete. Baseline offset: {baseline_offset:.5f}s")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    monitor()