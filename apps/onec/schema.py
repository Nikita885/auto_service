from drf_spectacular.extensions import OpenApiAuthenticationExtension


class OneCAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.onec.authentication.OneCKeyAuthentication"
    name = "oneCKeyAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey", "in": "header", "name": "Authorization",
            "description": "OneC <ключ обмена>; JWT сотрудника сюда не подходит.",
        }
