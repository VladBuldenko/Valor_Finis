import { File } from "expo-file-system";

import { apiRequest } from "../../api/api-client";

import type {
  PickedReceiptImage,
  Receipt,
  ReceiptConfirmInput,
  ReceiptConfirmResult,
} from "./receipt.types";

/**
 * Uploads a picked receipt image through the multipart upload endpoint.
 *
 * React Native's networking layer (as of RN 0.86 / Expo SDK 57) rejects a
 * plain `{ uri, name, type }` object appended to FormData at runtime with
 * "Unsupported FormDataPart implementation" -- the older convention of
 * passing an arbitrary object is no longer accepted, even though it can be
 * made to type-check. `expo-file-system`'s `File` implements the standard
 * `Blob` interface, so it is a genuine multipart part the runtime accepts,
 * and its `name`/`type` are derived from the real file at `image.uri`
 * rather than trusted from the picker's self-reported metadata. The API
 * client supplies the Supabase bearer token and lets the fetch runtime
 * generate the multipart boundary.
 */
export async function uploadReceipt(
  image: PickedReceiptImage,
): Promise<Receipt> {
  const file = new File(image.uri);
  const formData = new FormData();

  formData.append("file", file, file.name);

  return apiRequest<Receipt>("/api/v1/receipts/upload", {
    method: "POST",
    body: formData,
  });
}

/**
 * Starts OCR processing for a stored receipt.
 * Only receipts in `uploaded` or `failed` status can be processed;
 * the backend rejects any other status transition.
 */
export async function processReceipt(
  receiptId: string,
): Promise<Receipt> {
  return apiRequest<Receipt>(
    `/api/v1/receipts/${receiptId}/process`,
    {
      method: "POST",
    },
  );
}

/**
 * Returns a single receipt owned by the authenticated user.
 */
export async function getReceiptById(
  receiptId: string,
): Promise<Receipt> {
  return apiRequest<Receipt>(`/api/v1/receipts/${receiptId}`);
}

/**
 * Confirms a processed receipt, creating exactly one linked expense.
 * Only fields the user corrected need to be sent -- the backend falls
 * back to the OCR-detected values for anything omitted.
 */
export async function confirmReceipt(
  receiptId: string,
  confirmation: ReceiptConfirmInput,
): Promise<ReceiptConfirmResult> {
  return apiRequest<ReceiptConfirmResult>(
    `/api/v1/receipts/${receiptId}/confirm`,
    {
      method: "POST",
      body: JSON.stringify(confirmation),
    },
  );
}
