import contextvars

user_role_var = contextvars.ContextVar("user_role", default="User")
user_email_var = contextvars.ContextVar("user_email", default="")
client_name_var = contextvars.ContextVar("client_name", default="Unknown")
