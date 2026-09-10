package users

// UserID is currently a string alias.
type UserID = string

func Lookup(id UserID) UserID {
	return id
}
