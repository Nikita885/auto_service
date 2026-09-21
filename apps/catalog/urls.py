from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.catalog.views import (
    CarMakeListView,
    CarModelListView,
    CarSearchView,
    ServicePointViewSet,
)

app_name = "catalog"

router = DefaultRouter()
router.register("service-points", ServicePointViewSet, basename="service-point")

urlpatterns = [
    path("cars/makes/", CarMakeListView.as_view(), name="car-makes"),
    path(
        "cars/makes/<uuid:make_id>/models/",
        CarModelListView.as_view(),
        name="car-models",
    ),
    path("cars/search/", CarSearchView.as_view(), name="car-search"),
    path("", include(router.urls)),
]
