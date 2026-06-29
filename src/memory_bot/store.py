from __future__ import annotations

import logging

import boto3
from boto3.dynamodb.conditions import Key
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

from memory_bot.models import Note

logger = logging.getLogger(__name__)


class Store:
    def __init__(self, table_name: str, dynamodb_resource=None):
        res = dynamodb_resource or boto3.resource("dynamodb")
        self._table = res.Table(table_name)

    @staticmethod
    def create_table(dynamodb_resource, table_name: str):
        return dynamodb_resource.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

    @staticmethod
    def _pk(user_id: int) -> str:
        return f"user#{user_id}"

    def put_note(self, user_id: int, note: Note) -> None:
        item = {
            "pk": self._pk(user_id),
            "sk": f"note#{note.created_at}#{note.note_id}",
            "note_id": note.note_id,
            "text": note.text,
            "category": note.category,
            "created_at": note.created_at,
        }
        if note.summary is not None:
            item["summary"] = note.summary
        if note.status is not None:
            item["status"] = note.status
        if note.due_at is not None:
            item["due_at"] = note.due_at
        self._table.put_item(Item=item)

    def mark_done(self, user_id: int, note_id: str) -> bool:
        """Set a note's status to 'done'. Returns True if found, False otherwise.

        Uses pagination to handle notes spanning multiple 1MB DynamoDB pages.
        """
        key_cond = Key("pk").eq(self._pk(user_id)) & Key("sk").begins_with("note#")
        exclusive_start_key = None

        while True:
            query_kwargs = {
                "KeyConditionExpression": key_cond,
            }
            if exclusive_start_key is not None:
                query_kwargs["ExclusiveStartKey"] = exclusive_start_key

            resp = self._table.query(**query_kwargs)

            for item in resp.get("Items", []):
                if item.get("note_id") == note_id:
                    self._table.update_item(
                        Key={"pk": item["pk"], "sk": item["sk"]},
                        UpdateExpression="SET #s = :done",
                        ExpressionAttributeNames={"#s": "status"},
                        ExpressionAttributeValues={":done": "done"},
                    )
                    return True

            # Check if there are more pages
            if "LastEvaluatedKey" not in resp:
                break
            exclusive_start_key = resp["LastEvaluatedKey"]

        return False

    def set_timezone(self, user_id: int, tz: str) -> None:
        self._table.put_item(Item={"pk": self._pk(user_id), "sk": "settings", "tz": tz})

    def get_timezone(self, user_id: int) -> str | None:
        resp = self._table.get_item(Key={"pk": self._pk(user_id), "sk": "settings"})
        item = resp.get("Item")
        return item.get("tz") if item else None

    def get_history(self, user_id: int) -> list[ModelMessage]:
        resp = self._table.get_item(Key={"pk": self._pk(user_id), "sk": "history"})
        item = resp.get("Item")
        if not item or "messages" not in item:
            return []
        try:
            return list(ModelMessagesTypeAdapter.validate_json(item["messages"]))
        except Exception:
            logger.exception("failed to deserialize history for user %s", user_id)
            return []

    def save_history(self, user_id: int, messages: list[ModelMessage]) -> None:
        blob = ModelMessagesTypeAdapter.dump_json(messages).decode()
        self._table.put_item(
            Item={"pk": self._pk(user_id), "sk": "history", "messages": blob}
        )

    def clear_history(self, user_id: int) -> None:
        self._table.delete_item(Key={"pk": self._pk(user_id), "sk": "history"})

    def query_notes(
        self, user_id: int, category: str | None = None, status: str | None = None
    ) -> list[Note]:
        # Paginate through all results; DynamoDB limits to 1 MB per page
        all_items = []
        # Scope to note items only; the user pk also holds a "settings" item.
        key_cond = Key("pk").eq(self._pk(user_id)) & Key("sk").begins_with("note#")
        exclusive_start_key = None

        while True:
            query_kwargs = {
                "KeyConditionExpression": key_cond,
                "ScanIndexForward": False,  # newest first
            }
            if exclusive_start_key is not None:
                query_kwargs["ExclusiveStartKey"] = exclusive_start_key

            resp = self._table.query(**query_kwargs)
            all_items.extend(resp.get("Items", []))

            # Check if there are more pages
            if "LastEvaluatedKey" not in resp:
                break
            exclusive_start_key = resp["LastEvaluatedKey"]

        notes = [
            Note(
                note_id=i["note_id"],
                text=i["text"],
                category=i["category"],
                created_at=i["created_at"],
                summary=i.get("summary"),
                status=i.get("status"),
                due_at=i.get("due_at"),
            )
            for i in all_items
        ]
        if category is not None:
            notes = [n for n in notes if n.category == category]
        if status is not None:
            notes = [n for n in notes if n.status == status]
        return notes
