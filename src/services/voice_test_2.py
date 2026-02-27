import subprocess

def download_voice_by_curl(key: str, out_file="001.wav"):
    cmd = [
        "curl",
        "-X", "POST",
        "-H", "Content-Type: application/json",
        "-d", f'{{"key":"{key}"}}',
        "-o", out_file,
        "http://188.107.245.45:18888/saas/agent-api/download-voice"
    ]
    subprocess.run(cmd, check=True)

download_voice_by_curl("cTRBQ3hTcituUFdHamQyNEVRQ3p4RjdvblhNdGtVakNRNUVXenFIditTdkxFQ05yZndVd040L3M0UStQektqQ1UwYndXUHRHVUF1dXl2VnI0czhmY0JGMFEyL0dnTGpLdUxjNjdTWVEvSWNTMDBYMWdLUjBvY0YydUpUWk0yWnNsc2ZRWGkrZDRTRTY1RVBVcXFNQnhNOGtJSVNxYnR0MGxvc0VrSTRwenlYcW9HUjNzMFNldGtZdWJrWkpoOG9VRmpPZUhobnpSYkxJRnRGc0R1QWhWWDRMdjZDdFBGTGJsd05pcHNzMDArbWFxMk1UYWZWOXZVdXJlcUxldEU5WFVpWUVHL1NPd1g0R0tHRm1oVjNVZzhuZjRwY09RVXN4cldwSkZVaEM0UlVYSzhKS094TXhmMlQ3Q3NMcnFUVFYrZ3lwdmZUY3VHa1RMcU1xU2xrYm5iZCtCNzlOZkMwTDJReEIwcWFyNGQ4bktFS0VFYUQ0Z2VUUnYxdG8zN0RGeXduN1IzSEJwU2hPNmd0bTVNSE5XWlh4cXhNZkczdHQvWEh5QUlBZnA3az0=")
