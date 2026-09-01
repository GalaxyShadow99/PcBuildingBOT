import sys

from database import *

if __name__ == "__main__":
    initDb()
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python add_search.py list                      # Lister la watchlist")
        print("  python add_search.py add \"mot-clé\" 150         # Ajouter (mot-clé, prix_max)")
        print("  python add_search.py delete 3                  # Supprimer par ID")
        print("  python add_search.py deleteDB                  # Supprimer toutes les annonces")
        sys.exit(1)
        
    cmd = sys.argv[1]
    if cmd == "list":
        listItems()
    elif cmd == "add" and len(sys.argv) >= 4:
        addItem(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else 15)
    elif cmd == "delete" and len(sys.argv) >= 3:
        deleteItem(sys.argv[2])
    elif cmd == "deleteDB":
        deleteDB()
    else:
        print("Commande ou arguments invalides.")
