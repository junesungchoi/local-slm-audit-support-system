#!/usr/bin/env bash
# Sets up the current project directory as a Git repository and prepares it for GitHub.
# Usage: bash setup_github_repository.sh https://github.com/OWNER/local-slm-audit-support-system.git

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_URL="${1:-}"

if ! command -v git >/dev/null 2>&1; then
  echo "Git is not installed. Install Git for Windows, then run this script again."
  exit 1
fi

if [[ -z "$(git config --global user.name || true)" || -z "$(git config --global user.email || true)" ]]; then
  echo "Set your Git identity first, then run this script again:"
  echo "  git config --global user.name \"Your Name\""
  echo "  git config --global user.email \"your-email@example.com\""
  exit 1
fi

cd "$PROJECT_DIR"

if [[ ! -d .git ]]; then
  # Required project folders. .gitkeep allows otherwise empty folders to be tracked.
  mkdir -p src docs design tests sample_data outputs
  touch docs/.gitkeep design/.gitkeep tests/.gitkeep outputs/.gitkeep

  # Put the existing prototype files in the requested structure.
  [[ -f app.py ]] && mv app.py src/app.py
  [[ -f core.py ]] && mv core.py src/core.py
  [[ -f sample_rules.json ]] && mv sample_rules.json sample_data/sample_rules.json

  cat > .gitignore <<'EOF'
# Python and operating-system files
__pycache__/
*.py[cod]
.venv/
venv/
.env
.DS_Store
Thumbs.db

# Generated local project files
cases/
criteria/
*.log
*.tmp

# Audit evidence is excluded by default. Only approved synthetic test files
# placed in sample_data may be committed.
*.csv
*.txt
!sample_data/**/*.csv
!sample_data/**/*.txt

# Sensitive or large files: never commit actual audit material or local models
*.xlsx
*.xls
*.docx
*.pdf
*.zip
*.7z
*.bin
*.gguf
*.safetensors
*.pt
*.pth
*.onnx
*.key
*.pem
secrets/
credentials/
EOF

  git init -b main
  git add README.md requirements.txt src docs design tests sample_data outputs .gitignore setup_github_repository.sh
  git commit -m "Initialize project structure and offline audit prototype"
  git branch development

  echo
  echo "Local repository created successfully."
  echo "Branches created: main and development"
  echo
else
  echo "An existing local repository was found. Its files were left unchanged."
fi

if git remote get-url origin >/dev/null 2>&1; then
  REMOTE_URL="$(git remote get-url origin)"
  echo "Existing GitHub remote found: $REMOTE_URL"
else
  echo "Next, create an EMPTY GitHub repository in the browser."
  echo "Do not select Add a README, .gitignore, or license on GitHub."
  echo
fi

if [[ -z "$REMOTE_URL" ]]; then
  read -r -p "Paste the GitHub HTTPS repository URL, then press Enter: " REMOTE_URL
fi

if [[ ! "$REMOTE_URL" =~ ^https://github\.com/.+/.+\.git$ ]]; then
  echo "The URL should look like: https://github.com/OWNER/REPOSITORY.git"
  echo "Repository creation is complete locally. Re-run with the correct URL to connect and push."
  exit 0
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "$REMOTE_URL"
fi
git push -u origin main
git push -u origin development

echo
echo "Upload complete. Submit this URL: ${REMOTE_URL%.git}"
echo "Open the repository's Branches page and capture main and development for the assignment."
