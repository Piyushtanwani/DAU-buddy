import contextvars

user_role_var = contextvars.ContextVar("user_role", default="User")
