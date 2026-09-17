package users

func Store(id UserID) {
	_ = Lookup(id)
}
