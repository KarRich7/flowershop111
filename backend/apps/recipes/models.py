from django.db import models
from django.db.models import Q

from apps.inventory.models import InventoryItem


class BouquetRecipe(models.Model):
    """Рецептура готового букета: из каких материалов собирается одна единица."""

    bouquet_item = models.OneToOneField(InventoryItem, on_delete=models.CASCADE, related_name="recipe")
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bouquet_recipes"

    def __str__(self):
        return f"Рецептура: {self.bouquet_item.name}"


class RecipeComponent(models.Model):
    recipe = models.ForeignKey(BouquetRecipe, on_delete=models.CASCADE, related_name="components")
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="used_in_recipes")
    quantity = models.PositiveIntegerField()

    class Meta:
        db_table = "recipe_components"
        constraints = [
            models.UniqueConstraint(fields=["recipe", "item"], name="uniq_recipe_component"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="recipe_component_qty_positive"),
        ]
