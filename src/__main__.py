from src.infrastructure.console.menu import MailApp
from src.main.dependency_injection import container

if __name__ == "__main__":
    try:
        MailApp(container).run()
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")
