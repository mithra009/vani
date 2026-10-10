-- Signed-upload browsers insert objects as their own user; the media bucket needs
-- an INSERT policy or every direct upload fails with a row-level-security 403.

drop policy if exists "media_objects_insert_own" on storage.objects;
create policy "media_objects_insert_own" on storage.objects
  for insert with check (
    bucket_id = 'media' and auth.uid()::text = (storage.foldername(name))[1]
  );
