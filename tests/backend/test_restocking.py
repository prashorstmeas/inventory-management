"""
Tests for restocking API endpoints.
"""
import pytest
from datetime import datetime


class TestRestockRecommendationsEndpoint:
    """Test suite for the restock recommendations endpoint."""

    def test_get_recommendations_default_structure(self, client):
        """Test that recommendations response has the expected top-level structure."""
        response = client.get("/api/restocking/recommendations?budget=10000")
        assert response.status_code == 200

        data = response.json()
        assert "budget" in data
        assert "recommended_items" in data
        assert "total_cost" in data
        assert "remaining_budget" in data
        assert "skipped_count" in data
        assert isinstance(data["recommended_items"], list)

    def test_recommendations_within_budget(self, client):
        """Test that total recommended cost never exceeds the given budget."""
        response = client.get("/api/restocking/recommendations?budget=100")
        assert response.status_code == 200

        data = response.json()
        assert data["total_cost"] <= 100

    def test_recommendations_zero_budget_returns_empty(self, client):
        """Test that a budget of 0 yields no recommended items."""
        response = client.get("/api/restocking/recommendations?budget=0")
        assert response.status_code == 200

        data = response.json()
        assert data["recommended_items"] == []
        assert data["total_cost"] == 0

    def test_recommendations_missing_budget_param(self, client):
        """Test that omitting the required budget query param returns 422."""
        response = client.get("/api/restocking/recommendations")
        assert response.status_code == 422

    def test_recommendations_negative_budget_rejected(self, client):
        """Test that a negative budget is rejected with 422."""
        response = client.get("/api/restocking/recommendations?budget=-100")
        assert response.status_code == 422

    def test_recommendation_item_fields(self, client):
        """Test that each recommended item has all expected fields."""
        response = client.get("/api/restocking/recommendations?budget=1000000")
        data = response.json()

        required_fields = [
            "item_sku", "item_name", "trend", "current_demand",
            "forecasted_demand", "restock_qty", "unit_cost", "item_cost"
        ]
        assert len(data["recommended_items"]) > 0
        for item in data["recommended_items"]:
            for field in required_fields:
                assert field in item, f"Missing field: {field}"

    def test_recommendations_skip_negative_or_zero_gap(self, client):
        """Test that items with no positive demand gap are never recommended."""
        response = client.get("/api/restocking/recommendations?budget=1000000")
        data = response.json()

        for item in data["recommended_items"]:
            assert item["restock_qty"] > 0

    def test_recommendations_only_includes_inventory_matched_skus(self, client):
        """Test that every recommended SKU exists in inventory (needed to price it)."""
        inv_response = client.get("/api/inventory")
        inv_skus = {item["sku"] for item in inv_response.json()}

        response = client.get("/api/restocking/recommendations?budget=1000000")
        data = response.json()

        for item in data["recommended_items"]:
            assert item["item_sku"] in inv_skus

    def test_recommendations_ranked_by_trend_priority(self, client):
        """Test that items are ordered by trend tier (increasing > stable > decreasing)."""
        response = client.get("/api/restocking/recommendations?budget=1000000")
        data = response.json()

        trend_rank = {"increasing": 0, "stable": 1, "decreasing": 2}
        ranks = [trend_rank.get(item["trend"], 3) for item in data["recommended_items"]]
        assert ranks == sorted(ranks)

    def test_recommendations_item_cost_calculation(self, client):
        """Test that item_cost equals restock_qty * unit_cost."""
        response = client.get("/api/restocking/recommendations?budget=1000000")
        data = response.json()

        for item in data["recommended_items"]:
            expected_cost = round(item["restock_qty"] * item["unit_cost"], 2)
            assert abs(item["item_cost"] - expected_cost) < 0.01

    def test_recommendations_increasing_budget_never_decreases_items(self, client):
        """Test that a larger budget recommends at least as many items as a smaller one."""
        small_response = client.get("/api/restocking/recommendations?budget=200")
        large_response = client.get("/api/restocking/recommendations?budget=8000")

        small_count = len(small_response.json()["recommended_items"])
        large_count = len(large_response.json()["recommended_items"])
        assert large_count >= small_count


class TestPlaceRestockOrderEndpoint:
    """Test suite for the place restock order endpoint."""

    def test_place_order_success(self, client):
        """Test successfully placing a restock order."""
        payload = {
            "budget": 1000,
            "items": [
                {"sku": "PSU-501", "name": "5V 10A Switching Power Supply", "quantity": 2, "unit_price": 18.99}
            ]
        }
        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 201

        order = response.json()["order"]
        assert order["source"] == "restock"
        assert order["status"] == "Processing"
        assert order["lead_time_days"] == 14
        assert order["customer"] == "Internal Restocking"
        assert abs(order["total_value"] - 37.98) < 0.01

    def test_place_order_empty_items_rejected(self, client):
        """Test that submitting an order with no items returns 400."""
        response = client.post("/api/restocking/orders", json={"budget": 1000, "items": []})
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data

    def test_place_order_missing_items_field(self, client):
        """Test that omitting the required items field returns 422."""
        response = client.post("/api/restocking/orders", json={"budget": 100})
        assert response.status_code == 422

    def test_placed_order_appears_in_get_orders(self, client):
        """Test that a newly submitted restock order shows up in GET /api/orders."""
        payload = {
            "budget": 500,
            "items": [{"sku": "PSU-501", "name": "5V 10A Switching Power Supply", "quantity": 1, "unit_price": 18.99}]
        }
        post_response = client.post("/api/restocking/orders", json=payload)
        new_order_id = post_response.json()["order"]["id"]

        get_response = client.get("/api/orders")
        all_ids = [order["id"] for order in get_response.json()]
        assert new_order_id in all_ids

    def test_placed_order_expected_delivery_matches_lead_time(self, client):
        """Test that expected_delivery is exactly lead_time_days after order_date."""
        payload = {
            "budget": 100,
            "items": [{"sku": "DRV-405", "name": "H-Bridge Motor Driver", "quantity": 1, "unit_price": 22.0}]
        }
        response = client.post("/api/restocking/orders", json=payload)
        order = response.json()["order"]

        order_date = datetime.fromisoformat(order["order_date"])
        expected_delivery = datetime.fromisoformat(order["expected_delivery"])
        assert (expected_delivery - order_date).days == order["lead_time_days"]

    def test_place_order_total_value_calculation(self, client):
        """Test that total_value is the sum of quantity * unit_price across items."""
        payload = {
            "budget": 5000,
            "items": [
                {"sku": "PCB-002", "name": "Dual Layer PCB Assembly", "quantity": 10, "unit_price": 29.99},
                {"sku": "MCU-401", "name": "8-bit Microcontroller", "quantity": 5, "unit_price": 8.25}
            ]
        }
        response = client.post("/api/restocking/orders", json=payload)
        order = response.json()["order"]

        expected_total = round(10 * 29.99 + 5 * 8.25, 2)
        assert abs(order["total_value"] - expected_total) < 0.01

    def test_place_order_unknown_sku_rejected(self, client):
        """Test that an item referencing a SKU not in inventory is rejected."""
        payload = {
            "budget": 1000,
            "items": [{"sku": "NOT-A-REAL-SKU", "name": "Fake Item", "quantity": 1, "unit_price": 10.0}]
        }
        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data

    def test_place_order_non_positive_quantity_rejected(self, client):
        """Test that a non-positive quantity is rejected with 422."""
        payload = {
            "budget": 100,
            "items": [{"sku": "PSU-501", "name": "5V 10A Switching Power Supply", "quantity": 0, "unit_price": 18.99}]
        }
        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 422

    def test_place_order_non_positive_unit_price_rejected(self, client):
        """Test that a non-positive unit_price is rejected with 422."""
        payload = {
            "budget": 100,
            "items": [{"sku": "PSU-501", "name": "5V 10A Switching Power Supply", "quantity": 1, "unit_price": -5.0}]
        }
        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 422

    def test_place_order_generates_unique_order_number(self, client):
        """Test that consecutive restock orders get distinct order numbers and ids."""
        payload = {
            "budget": 100,
            "items": [{"sku": "ACC-206", "name": "3-Axis Accelerometer", "quantity": 1, "unit_price": 156.0}]
        }
        first = client.post("/api/restocking/orders", json=payload).json()["order"]
        second = client.post("/api/restocking/orders", json=payload).json()["order"]

        assert first["id"] != second["id"]
        assert first["order_number"] != second["order_number"]
