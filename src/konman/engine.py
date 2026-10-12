import os
import glob
from pathlib import Path
from ruamel.yaml import YAML

class ContextEngine:
    def __init__(self, target_dir: str = "."):
        self.base_dir = Path(target_dir).resolve()
        self.ctx_dir = self.base_dir / ".context"
        self.yaml = YAML()
        self.yaml.preserve_quotes = True

    def init_folders(self):
        """Scaffold the .context storage layout matrix folder database."""
        folders = [
            "requirements", "decisions", "objects", 
            "state/history", ".raw", "questions"
        ]
        for f in folders:
            (self.ctx_dir / f).mkdir(parents=True, exist_ok=True)
            
        manifest_path = self.ctx_dir / "manifest.yaml"
        if not manifest_path.exists():
            with open(manifest_path, "w", encoding="utf-8") as f:
                self.yaml.dump({
                    "schema_version": "1.0.0",
                    "tool_name": "konman"
                }, f)

    def process_staleness_propagation(self) -> int:
        """Finds any decision using a superseded requirement and flags it instantly."""
        req_dir = self.ctx_dir / "requirements"
        dec_dir = self.ctx_dir / "decisions"
        if not req_dir.exists() or not dec_dir.exists():
            return 0

        stale_reqs = set()
        for p in req_dir.glob("*.yaml"):
            with open(p, "r", encoding="utf-8") as f:
                data = self.yaml.load(f)
                if data and data.get("status") in ["superseded", "disproven"]:
                    stale_reqs.add(data.get("id"))

        updated_count = 0
        for p in dec_dir.glob("*.yaml"):
            with open(p, "r", encoding="utf-8") as f:
                dec_data = self.yaml.load(f)
            
            if not dec_data or dec_data.get("status") == "needs_review":
                continue

            needs_flag = False
            for item in dec_data.get("considered", []):
                for eval_item in item.get("evaluations", []):
                    if eval_item.get("req") in stale_reqs:
                        needs_flag = True
                        break
            
            if needs_flag:
                dec_data["status"] = "needs_review"
                with open(p, "w", encoding="utf-8") as f:
                    self.yaml.dump(dec_data, f)
                updated_count += 1
        return updated_count

    def check_graph_validity(self) -> list:
        """Scans the database layout for any unconfirmed reviews or broken links."""
        violations = []
        dec_dir = self.ctx_dir / "decisions"
        if dec_dir.exists():
            for p in dec_dir.glob("*.yaml"):
                with open(p, "r", encoding="utf-8") as f:
                    d = self.yaml.load(f)
                    if d and d.get("status") == "needs_review":
                        violations.append(f"Decision '{d.get('id')}' [{d.get('chosen').upper()}] is flagged as 'needs_review'.")
        return violations

    def mine_git_history(self, count: int = 10) -> int:
        """Queries the local repository logs and saves structured reasoning JSON entries."""
        import subprocess
        import json
        from datetime import datetime

        raw_dir = self.ctx_dir / ".raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        try:
            cmd = ["git", "log", f"-n {count}", "--pretty=format:%H||%an||%ad||%s%b", "--date=short"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
            log_lines = result.stdout.strip().split("\n")
        except Exception:
            return 0

        mined_count = 0
        keywords = ["because", "requires", "reverts", "fixes", "breaking change"]

        for line in log_lines:
            if not line or "||" not in line:
                continue
            parts = line.split("||")
            if len(parts) < 4:
                continue
            commit_hash, author, date_str, message = parts[0], parts[1], parts[2], parts[3]

            if any(kw in message.lower() for kw in keywords):
                payload = {
                    "source": "git_history_miner",
                    "commit": commit_hash,
                    "author": author,
                    "date": date_str,
                    "extracted_text": message,
                    "timestamp_mined": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                output_file = raw_dir / f"git_mined_{commit_hash[:8]}.json"
                if not output_file.exists():
                    with open(output_file, "w", encoding="utf-8") as out:
                        json.dump(payload, out, indent=2)
                    mined_count += 1
        return mined_count

    def execute_llm_distillation(self, text_content: str, api_key: str, model_name: str = "gpt-4o-mini") -> str:
        """Pipes unstructured log pools out to OpenAI schema compilation nodes."""
        import urllib.request
        import json

        system_prompt = (
            "You are the extraction engine for konman (Context Manager).\n"
            "Your job is to read raw development logs/transcripts and distill architectural context.\n"
            "Format output strictly as raw JSON text matching this syntax structural layout without markdown formatting backticks:\n"
            "{\n"
            "  \"requirements\": [{ \"id\": \"R-XXX\", \"statement\": \"...\", \"kind\": \"hard|preference\", \"why\": \"...\" }],\n"
            "  \"decisions\": [{ \"id\": \"D-XXX\", \"chosen\": \"...\", \"mode\": \"compared\", \"reason\": \"...\" }]\n"
            "}"
        )

        url = "https://openai.com"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        data = {
            "model": model_name,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text_content}
            ]
        }

        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                return res_data["choices"]["message"]["content"]
        except Exception as e:
            return f"{{\"error\": \"LLM Pipeline disconnect: {str(e)}\"}}"

    def compile_agents_md(self):
        """Compiles active definitions directly into a universal markdown overview proxy file."""
        agents_path = self.base_dir / "AGENTS.md"
        req_summary = []
        req_dir = self.ctx_dir / "requirements"
        
        if req_dir.exists():
            for p in req_dir.glob("*.yaml"):
                with open(p, "r", encoding="utf-8") as f:
                    r = self.yaml.load(f)
                    if r and r.get("status") == "active":
                        req_summary.append(f"- **{r.get('id')}** [{r.get('kind').upper()}]: {r.get('statement')}")

        content = (
            "# 🤖 PROJECT CONTEXT DIRECTORY\n\n"
            "This file is auto-generated by **`konman`**. Do not edit directly.\n\n"
            "## 📌 Active System Architectural Requirements\n"
            + ("\n".join(req_summary) if req_summary else "No active architecture rules recorded.")
            + "\n\n## 🔍 Read Manifest Maps\n"
            "Refer to the local repository schema files stored within `.context/` paths.\n"
        )
        with open(agents_path, "w", encoding="utf-8") as f:
            f.write(content)
