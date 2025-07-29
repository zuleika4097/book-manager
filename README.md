# 📚 Book Manager

A Python project for managing a collection of books. This application allows you to manage books. It's designed to be modular, easy to use, and extensible for a variety of use cases such as personal libraries, academic references, or inventory systems.

## 🚀 Getting Started

These instructions will help you set up the project on your local machine for development and testing purposes.

### 📦 Prerequisites

- [Python](https://www.python.org/) 3.12+
- [uv](https://github.com/astral-sh/uv) (a fast Python package manager)

You can install `uv` by running:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then install python if you need to:
```bash
uv python install 3.12 # or 3.13
```

See the uv [installation guide](https://docs.astral.sh/uv/getting-started/features/) for more options.

## 🛠️ Setup

### 1. Clone the repository
```bash
git clone https://github.com/your-username/book-manager.git
cd book-manager
```
### 2. Create a virtual environment:
```bash
uv venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
```
### 3. Run the application
```bash
uv run python main.py
```

## 📁 Project Structure
```bash
book-manager/
├── book_manager/        
│   ├── __init__.py
│   ├── models.py
│   ├── manager.py
│   └── ...
├── main.py              # Entry point
├── pyproject.toml       # Project metadata
└── README.md
```

## 📄 License
This project is licensed under the MIT License. See the [LICENSE](LICENSE.txt) file for details.

## 🙌 Contributing
Contributions are welcome! Please open issues or pull requests as needed.
