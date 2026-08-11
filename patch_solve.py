with open("solve.py", "r") as f:
    content = f.read()

content = content.replace("/mnt/agents/output/arkhe-n-v1.4", "./arkhe-n-v1.4")

with open("solve.py", "w") as f:
    f.write(content)
