"""Tests for serializers."""

import pytest
import json
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID, uuid4
from pydantic import BaseModel, ValidationError

from tchu_tchu.serializers.pydantic_serializer import PydanticSerializer
from tchu_tchu.utils.error_handling import SerializationError


class TestModel(BaseModel):
    """Test Pydantic model."""

    name: str
    age: int
    email: str


class TestPydanticSerializer:
    """Test cases for PydanticSerializer."""

    def test_serialize_dict(self):
        """Test serializing a dictionary."""
        serializer = PydanticSerializer()
        data = {"name": "John", "age": 30}

        result = serializer.serialize(data)

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["name"] == "John"
        assert parsed["age"] == 30

    def test_serialize_pydantic_model(self):
        """Test serializing a Pydantic model."""
        serializer = PydanticSerializer()
        model = TestModel(name="John", age=30, email="john@example.com")

        result = serializer.serialize(model)

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["name"] == "John"
        assert parsed["age"] == 30
        assert parsed["email"] == "john@example.com"

    def test_serialize_with_model_class(self):
        """Test serializing with a specific model class."""
        serializer = PydanticSerializer(TestModel)
        data = {"name": "John", "age": 30, "email": "john@example.com"}

        result = serializer.serialize(data)

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["name"] == "John"

    def test_serialize_special_types(self):
        """Test serializing special Python types."""
        serializer = PydanticSerializer()
        test_uuid = uuid4()
        test_date = date.today()
        test_datetime = datetime.now()
        test_decimal = Decimal("10.50")

        data = {
            "uuid": test_uuid,
            "date": test_date,
            "datetime": test_datetime,
            "decimal": test_decimal,
            "set": {1, 2, 3},
            "bytes": b"hello",
        }

        result = serializer.serialize(data)
        parsed = json.loads(result)

        assert parsed["uuid"] == str(test_uuid)
        assert parsed["date"] == test_date.isoformat()
        assert parsed["datetime"] == test_datetime.isoformat()
        assert parsed["decimal"] == float(test_decimal)
        assert set(parsed["set"]) == {1, 2, 3}
        assert parsed["bytes"] == "hello"

    def test_deserialize_string(self):
        """Test deserializing a JSON string."""
        serializer = PydanticSerializer()
        json_str = '{"name": "John", "age": 30}'

        result = serializer.deserialize(json_str)

        assert isinstance(result, dict)
        assert result["name"] == "John"
        assert result["age"] == 30

    def test_deserialize_bytes(self):
        """Test deserializing bytes."""
        serializer = PydanticSerializer()
        json_bytes = b'{"name": "John", "age": 30}'

        result = serializer.deserialize(json_bytes)

        assert isinstance(result, dict)
        assert result["name"] == "John"
        assert result["age"] == 30

    def test_deserialize_with_model_class(self):
        """Test deserializing with model validation."""
        serializer = PydanticSerializer(TestModel)
        json_str = '{"name": "John", "age": 30, "email": "john@example.com"}'

        result = serializer.deserialize(json_str)

        assert isinstance(result, TestModel)
        assert result.name == "John"
        assert result.age == 30
        assert result.email == "john@example.com"

    def test_serialize_invalid_data_with_model(self):
        """Test serialization error with invalid data."""
        serializer = PydanticSerializer(TestModel)
        invalid_data = {"name": "John"}  # Missing required fields

        with pytest.raises(SerializationError):
            serializer.serialize(invalid_data)

    def test_deserialize_invalid_json(self):
        """Test deserialization error with invalid JSON."""
        serializer = PydanticSerializer()
        invalid_json = '{"name": "John", "age":}'

        with pytest.raises(SerializationError):
            serializer.deserialize(invalid_json)

    def test_deserialize_invalid_data_with_model(self):
        """Test deserialization error with model validation."""
        serializer = PydanticSerializer(TestModel)
        json_str = '{"name": "John", "age": "not_a_number", "email": "invalid_email"}'

        with pytest.raises(SerializationError):
            serializer.deserialize(json_str)
