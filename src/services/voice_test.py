import requests
import json

URL = "http://188.107.245.45:18888/saas/agent-api/download-voice?key=cTRBQ3hTcituUFdHamQyNEVRQ3p4RjdvblhNdGtVakNRNUVXenFIditTdkxFQ05yZndVd040L3M0UStQektqQ1UwYndXUHRHVUF1dXl2VnI0czhmY0JGMFEyL0dnTGpLdUxjNjdTWVEvSWNTMDBYMWdLUjBvY0YydUpUWk0yWnNsc2ZRWGkrZDRTRTY1RVBVcXFNQnhNOGtJSVNxYnR0MGxvc0VrSTRwenlYcW9HUjNzMFNldGtZdWJrWkpoOG9VRmpPZUhobnpSYkxJRnRGc0R1QWhWWDRMdjZDdFBGTGJsd05pcHNzMDArbWFxMk1UYWZWOXZVdXJlcUxldEU5WFVpWUVHL1NPd1g0R0tHRm1oVjNVZzhuZjRwY09RVXN4cldwSkZVaEM0UlVYSzhKS094TXhmMlQ3Q3NMcnFUVFYrZ3lwdmZUY3VHa1RMcU1xU2xrYm5iZCtCNzlOZkMwTDJReEIwcWFyNGQ4bktFS0VFYUQ0Z2VUUnYxdG8zN0RGeXduN1IzSEJwU2hPNmd0bTVNSE5XWlh4cXhNZkczdHQvWEh5QUlBZnA3az0="

def test_download_voice():
    #payload = json.dumps({"key": key})

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiIxIiwianRpIjoiZDE5NGUyMDhkNmZjZjFiYTIxYjYwZGQ2NWQ2ZTU2ODlkYzFkOTAxMzk5ZTg3ZWJiZGVlYWFmNGFhNDA0YzVlMTllZDQwODc5ZmIwNzc2NWQiLCJpYXQiOjE3NTgzNjAyMzMsIm5iZiI6MTc1ODM2MDIzMywiZXhwIjoxNzg5ODk2MjMzLCJzdWIiOiI5YWEyYzcyMi0xMmJhLTRkOWMtODA1Ni03NTc0NjFjZGVkNWUiLCJzY29wZXMiOltdfQ.tQAr3M1WgUv-YbgFZuNSiMQI5j5Mlw5vw3s7Pcwh_XRo-n1UE08AaHEIHCjHxKAcy1oYGzPrEkp8W0dP9oh_acxtoAw-7_6NXintBSrCF8tESpDvBF2Sr1yxHIVmOdXQkAbGvbnGnTwKedNq0jUqqumTjABj1odi1WoX1_KAQ8hs7RSpYvXogk9D46tRlgrGRQS7JdbrmhHy-FvYrhG4kDM2BlHlQ-zH5suOGE6X_yewi0ENvvq1AQkSclApB4QsyeUpAn-l2LsM4QaSRg_wYDsnzeJkEKfKQMDEQIOudYP1jPjzwVgQBRMi_SBKRojv8KruuXl-JXcvVse_HXiM9yw_Kl-9vEnWL-o-eugyFV35CoSU7svvc2YFSL1JCCSD3GvitutchrorxqsYrPSF6Wgud8pGFyxICI61LmiWjLEs0xriXcvUA1Cr7o_pzj--fZFq4LvBM7XUNL6O6wW585rdLhryjunpjboQWzIn7-NzZ8vk-TObx1Pm4c75ENm0wAh7pHDz8lAx4rFU3iPBnW5dDH4N36YbQT2zXooiAmNxzJ6IXFvCWxX6D_ViRF6iHrFyl7jNNwYQcpyX_HjlAzNwJEGCTuQs9JEYBUgb0M4wsR-oIAvUCM6fndEOk2H3xITu1sfAMKGWBnKtHqNPoEwklwHTDoqY24DFkYZhhuA",
    }

    resp = requests.get(
        URL,
        #data=payload,      # ❗ 注意：不是 json=
        headers=headers,
        timeout=30,
    )

    print("Status:", resp.status_code)
    print("Content-Type:", resp.headers.get("Content-Type"))
    print("Length:", len(resp.content))

    if (
        resp.status_code == 200
        and resp.headers.get("Content-Type", "").startswith("audio")
        and resp.content[:4] == b"RIFF"
    ):
        with open("001.wav", "wb") as f:
            f.write(resp.content)
        print("✓ 音频下载成功")
    else:
        print("✗ 下载失败，返回内容：")
        print(resp.text[:500])

if __name__ == "__main__":
    test_download_voice()
    #test_download_voice("cTRBQ3hTcituUFdHamQyNEVRQ3p4RjdvblhNdGtVakNRNUVXenFIditTdkxFQ05yZndVd040L3M0UStQektqQ1UwYndXUHRHVUF1dXl2VnI0czhmY0JGMFEyL0dnTGpLdUxjNjdTWVEvSWNTMDBYMWdLUjBvY0YydUpUWk0yWnNsc2ZRWGkrZDRTRTY1RVBVcXFNQnhNOGtJSVNxYnR0MGxvc0VrSTRwenlYcW9HUjNzMFNldGtZdWJrWkpoOG9VRmpPZUhobnpSYkxJRnRGc0R1QWhWWDRMdjZDdFBGTGJsd05pcHNzMDArbWFxMk1UYWZWOXZVdXJlcUxldEU5WFVpWUVHL1NPd1g0R0tHRm1oVjNVZzhuZjRwY09RVXN4cldwSkZVaEM0UlVYSzhKS094TXhmMlQ3Q3NMcnFUVFYrZ3lwdmZUY3VHa1RMcU1xU2xrYm5iZCtCNzlOZkMwTDJReEIwcWFyNGQ4bktFS0VFYUQ0Z2VUUnYxdG8zN0RGeXduN1IzSEJwU2hPNmd0bTVNSE5XWlh4cXhNZkczdHQvWEh5QUlBZnA3az0=")
