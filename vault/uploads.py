import io
from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.files.uploadhandler import FileUploadHandler, StopUpload


class BoundedUploadHandler(FileUploadHandler):
    """Keep bounded plaintext uploads in memory, never in Django's temp directory."""
    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.buffer = io.BytesIO()

    def receive_data_chunk(self, raw_data, start):
        if start + len(raw_data) > settings.VAULT_MAX_BYTES:
            raise StopUpload(connection_reset=True)
        self.buffer.write(raw_data)
        return None

    def file_complete(self, file_size):
        self.buffer.seek(0)
        return InMemoryUploadedFile(self.buffer, self.field_name, self.file_name,
                                    self.content_type, file_size, self.charset)
