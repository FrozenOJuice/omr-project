class StorageService:
    def __init__(self, storage_repo):
        self.storage_repo = storage_repo

    def upload_file(self, file_bytes: bytes, filename: str) -> dict:
        if not filename.lower().endswith(".pdf"):
            raise ValueError("Unsupported file format. Upload .pdf files only.")

        storage_result = self.storage_repo.upload_file(file_bytes, filename)
        return {"status": "secured", "filename": storage_result["filename"]}

    def remove_file(self, filename: str) -> dict:
        return self.storage_repo.delete_file(filename)
