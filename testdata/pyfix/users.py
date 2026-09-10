from .store import lookup

UserID = str

def lookup_user(id: UserID) -> UserID:
    return lookup(id)
