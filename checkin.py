#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import datetime
import json
import os
import random
import sys
import time
import urllib.request
import urllib.parse

BASE = "https://api.trae.cn"

def _post(path, headers, body=""):
    import urllib.error
    req = urllib.request.Request(BASE + path, data=body.encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")

def get_token(session):
    headers = {"Cookie": "X-Cloudide-Session=" + session, "Referer": "https://www.trae.cn/", "Origin": "https://www.trae.cn", "User-Agent": "TraeCheckin/1.0", "Accept": "application/json, text/plain, */*"}
    status, text = _post("/cloudide/api/v3/common/GetUserToken", headers)
    data = json.loads(text)
    token = (data.get("Result") or {}).get("Token")
    if status == 401:
        raise RuntimeError("Session expired (HTTP 401)")
    if status != 200 or not token:
        raise RuntimeError("GetUserToken failed: HTTP %s %s" % (status, text[:200]))
    return token

def checkin(token, device_id):
    headers = {"Authorization": "Cloud-IDE-JWT " + token, "X-User-Region": "cn", "x-device-id": device_id, "Content-Type": "application/json", "User-Agent": "TraeCheckin/1.0"}
    status, text = _post("/trae/api/v2/ug/checkin_credits/claim", headers, "{}")
    try:
        return {"http": status, "body": json.loads(text)}
    except json.JSONDecodeError:
        return {"http": status, "body": {"raw": text}}

def notify_feishu(webhook, text):
    if not webhook:
        return None
    try:
        payload = json.dumps({"msg_type": "text", "content": {"text": text}}).encode("utf-8")
        req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except Exception:
        return None

def notify_serverchan(sendkey, title, desp):
    if not sendkey:
        return None
    try:
        url = "https://sctapi.ftqq.com/" + sendkey + ".send"
        body = urllib.parse.urlencode({"title": title[:32], "desp": desp}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except Exception:
        return None

def beijing_now_str():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

def iter_sessions():
    s = os.environ.get("TRAE_SESSION", "").strip()
    if s:
        yield 1, s, os.environ.get("TRAE_DEVICE_ID", "").strip()
    n = 2
    while True:
        s = os.environ.get("TRAE_SESSION_" + str(n), "").strip()
        if not s:
            break
        yield n, s, os.environ.get("TRAE_DEVICE_ID_" + str(n), "").strip()
        n += 1

def random_device_id():
    return str(random.randint(10**15, 10**16 - 1))

def main():
    accounts = list(iter_sessions())
    if not accounts:
        print("error: missing TRAE_SESSION")
        sys.exit(1)
    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    sc_sendkey = os.environ.get("SC_SENDKEY", "").strip()
    ok_names, fail_names = [], []
    all_ok = True
    for index, session, device_id in accounts:
        if index > 1:
            time.sleep(random.uniform(3, 6))
        name = "account " + str(index)
        device_id = device_id or random_device_id()
        print("[" + name + "] device_id=" + device_id)
        try:
            token = get_token(session)
            print("[" + name + "] got JWT, len=" + str(len(token)))
            result = checkin(token, device_id)
            body = result["body"]
            code = body.get("code", -1)
            attempt = 1
            while code == 9074 and attempt < 5:
                device_id = random_device_id()
                attempt += 1
                print("[" + name + "] risk 9074, retry " + str(attempt))
                time.sleep(random.uniform(0.8, 1.5))
                result = checkin(token, device_id)
                body = result["body"]
                code = body.get("code", -1)
            checked = body.get("checked_in", False)
            ok = (result["http"] == 200) and (code == 0 or checked)
            credits = body.get("credits", 0)
            if ok:
                print("[" + name + "] success, credits=" + str(credits))
                ok_names.append(name)
            else:
                reason = body.get("message") or ("HTTP " + str(result["http"]))
                print("[" + name + "] failed: " + reason)
                fail_names.append(name)
                all_ok = False
        except Exception as e:
            print("[" + name + "] error: " + str(e))
            fail_names.append(name)
            all_ok = False
    summary = ["Trae checkin result", "time: " + beijing_now_str()]
    if ok_names:
        summary.append("ok: " + ", ".join(ok_names))
    if fail_names:
        summary.append("fail: " + ", ".join(fail_names))
    if webhook and (ok_names or fail_names):
        notify_feishu(webhook, "\n".join(summary))
    if sc_sendkey and fail_names:
        sc_title = "TraeCheckin failed(" + str(len(fail_names)) + ")"
        sc_desp = "\n".join(summary)
        notify_serverchan(sc_sendkey, sc_title, sc_desp)
        print("ServerChan notification sent")
    if not all_ok:
        sys.exit(1)
    print("all done")

if __name__ == "__main__":
    main()
