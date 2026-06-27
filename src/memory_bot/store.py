from __future__ import annotations

import boto3
from boto3.dynamodb.conditions import Key

from memory_bot.models import Note


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
        self._table.put_item(Item=item)

    def query_notes(
        self, user_id: int, category: str | None = None, status: str | None = None
    ) -> list[Note]:
        # Paginate through all results; DynamoDB limits to 1 MB per page
        all_items = []
        key_cond = Key("pk").eq(self._pk(user_id))
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
            )
            for i in all_items
        ]
        if category is not None:
            notes = [n for n in notes if n.category == category]
        if status is not None:
            notes = [n for n in notes if n.status == status]
        return notes

    def distinct_categories(self, user_id: int) -> list[str]:
        return sorted({n.category for n in self.query_notes(user_id)})
