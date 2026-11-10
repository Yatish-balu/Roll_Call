import { apiClient } from "@/services/api/client";

export interface Room {
  room_id: string;
  name: string;
}

export interface RoomPage {
  items: Room[];
  total: number;
  limit: number;
  offset: number;
}

export interface RoomCreateParams {
  room_id: string;
  name: string;
}

export async function fetchRooms(params?: {
  limit?: number;
  offset?: number;
}): Promise<RoomPage> {
  return apiClient.get<RoomPage>("/api/v1/rooms", params);
}

export async function getRoom(roomId: string): Promise<Room> {
  return apiClient.get<Room>(`/api/v1/rooms/${encodeURIComponent(roomId)}`);
}

export async function createRoom(data: RoomCreateParams): Promise<Room> {
  return apiClient.post<Room>("/api/v1/rooms", data);
}

