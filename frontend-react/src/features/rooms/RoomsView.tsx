"use client";

import React, { useState, useCallback, useMemo } from "react";
import { fetchRooms, createRoom, type Room } from "@/services/api/rooms";
import { useAuth } from "@/hooks/useAuth";
import { useResource } from "@/hooks/useResource";
import { invalidate } from "@/services/api/cache";

const ROOMS_LIST_KEY = "/api/v1/rooms?limit=100";

export function RoomsView() {
  const { isAdmin } = useAuth();
  const roomsRes = useResource<{ items?: Room[]; total?: number }>(
    ROOMS_LIST_KEY,
    () => fetchRooms({ limit: 100 })
  );

  const rooms = useMemo(() => roomsRes.data?.items ?? [], [roomsRes.data]);
  const isLoading = roomsRes.isLoading && !roomsRes.data;
  const error = roomsRes.error
    ? roomsRes.error instanceof Error
      ? roomsRes.error.message
      : "Unable to load room allocations."
    : null;

  const loadRooms = useCallback(async () => {
    await roomsRes.refresh();
  }, [roomsRes]);

  // Search & Filter
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedType, setSelectedType] = useState("ALL");

  // Create Modal
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [roomId, setRoomId] = useState("");
  const [roomName, setRoomName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const filteredRooms = useMemo(() => {
    return rooms.filter((r) => {
      const matchesSearch =
        r.room_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        r.name.toLowerCase().includes(searchQuery.toLowerCase());
      if (!matchesSearch) return false;

      if (selectedType === "LAB") return r.name.toLowerCase().includes("lab");
      if (selectedType === "HALL") return !r.name.toLowerCase().includes("lab");
      return true;
    });
  }, [rooms, searchQuery, selectedType]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!roomId.trim() || !roomName.trim()) {
      setFormError("Both Room ID and Name are required.");
      return;
    }

    setIsSubmitting(true);
    setFormError(null);
    try {
      await createRoom({
        room_id: roomId.trim().toUpperCase(),
        name: roomName.trim(),
      });
      setIsCreateOpen(false);
      setRoomId("");
      setRoomName("");
      invalidate([ROOMS_LIST_KEY, "/api/v1/sessions"]);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setFormError(err.message);
      } else {
        setFormError("Failed to register room.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[#24251C] tracking-tight">Rooms & Facilities</h1>
          <p className="text-sm text-[#77735F] mt-0.5">
            Campus lecture halls, computing laboratories, and allocated capacity.
          </p>
        </div>
        {isAdmin ? (
          <button
            onClick={() => setIsCreateOpen(true)}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-[#3F451F] text-[#FBF8F0] text-sm font-semibold rounded-xl hover:bg-[#323719] transition-all shadow-sm cursor-pointer"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" />
            </svg>
            Add Room
          </button>
        ) : (
          <span className="px-3.5 py-1.5 rounded-xl bg-[#EDE8D8] text-[#77735F] text-xs font-semibold border border-[#E4DDCA]">
            Institutional Room Registry
          </span>
        )}
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-sm">
          <p className="text-xs uppercase font-bold text-[#77735F] tracking-wider">Total Rooms</p>
          <p className="text-2xl font-bold text-[#24251C] mt-1">{rooms.length}</p>
        </div>
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-sm">
          <p className="text-xs uppercase font-bold text-[#77735F] tracking-wider">Computing Labs</p>
          <p className="text-2xl font-bold text-[#6C5119] mt-1">
            {rooms.filter((r) => r.name.toLowerCase().includes("lab")).length}
          </p>
        </div>
        <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-sm">
          <p className="text-xs uppercase font-bold text-[#77735F] tracking-wider">Lecture Halls</p>
          <p className="text-2xl font-bold text-[#3F451F] mt-1">
            {rooms.filter((r) => !r.name.toLowerCase().includes("lab")).length}
          </p>
        </div>
      </div>

      {/* Search and Filters */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-4 shadow-sm flex flex-col md:flex-row gap-3">
        <div className="flex-1 relative">
          <input
            type="text"
            placeholder="Search by Room ID (e.g. A-201, Lab-2) or name..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-4 py-2.5 text-sm text-[#24251C] placeholder-[#77735F] focus:outline-none focus:border-[#3F451F]"
          />
        </div>
        <div className="flex items-center gap-2">
          {["ALL", "HALL", "LAB"].map((type) => (
            <button
              key={type}
              onClick={() => setSelectedType(type)}
              className={`px-3 py-2 rounded-xl text-xs font-semibold tracking-wide transition-all ${
                selectedType === type
                  ? "bg-[#3F451F] text-[#FBF8F0]"
                  : "bg-[#F2EDE0] text-[#77735F] hover:bg-[#EAE4D4]"
              }`}
            >
              {type === "ALL" ? "All Rooms" : type === "HALL" ? "Lecture Halls" : "Labs"}
            </button>
          ))}
        </div>
      </div>

      {/* Rooms Table */}
      <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl overflow-hidden shadow-sm">
        {isLoading ? (
          <div className="p-12 text-center text-[#77735F]">
            <div className="inline-block animate-spin w-6 h-6 border-2 border-[#3F451F] border-t-transparent rounded-full mb-2" />
            <p className="text-sm">Loading rooms...</p>
          </div>
        ) : error ? (
          <div className="p-10 text-center">
            <p className="text-sm text-red-600 mb-3">{error}</p>
            <button
              onClick={() => void loadRooms()}
              className="px-4 py-1.5 bg-[#3F451F] text-[#FBF8F0] text-xs font-semibold rounded-lg hover:bg-[#323719]"
            >
              Retry
            </button>
          </div>
        ) : filteredRooms.length === 0 ? (
          <div className="p-12 text-center text-[#77735F]">
            <p className="text-sm">No rooms found matching your search.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#F2EDE0] text-[#77735F] uppercase text-xs border-b border-[#E4DDCA]">
                <tr>
                  <th className="py-3 px-4 font-semibold">Room ID</th>
                  <th className="py-3 px-4 font-semibold">Name / Description</th>
                  <th className="py-3 px-4 font-semibold">Type</th>
                  <th className="py-3 px-4 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E4DDCA]/60 text-[#24251C]">
                {filteredRooms.map((room) => {
                  const isLab = room.name.toLowerCase().includes("lab");
                  return (
                    <tr key={room.room_id} className="hover:bg-[#F2EDE0]/50 transition-colors">
                      <td className="py-3.5 px-4 font-mono font-bold text-[#3F451F]">
                        {room.room_id}
                      </td>
                      <td className="py-3.5 px-4 font-medium">{room.name}</td>
                      <td className="py-3.5 px-4">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold ${
                            isLab
                              ? "bg-[#6C5119]/15 text-[#6C5119] border border-[#6C5119]/25"
                              : "bg-[#72785E]/15 text-[#3F451F] border border-[#72785E]/25"
                          }`}
                        >
                          {isLab ? "Computing Lab" : "Lecture Hall"}
                        </span>
                      </td>
                      <td className="py-3.5 px-4">
                        <span className="inline-flex items-center gap-1.5 text-xs text-emerald-700 font-medium">
                          <span className="w-2 h-2 rounded-full bg-emerald-500" />
                          Active
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create Modal */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-[#FBF8F0] border border-[#E4DDCA] rounded-2xl p-6 max-w-md w-full shadow-xl">
            <h3 className="text-lg font-bold text-[#24251C]">Add New Room</h3>
            <p className="text-xs text-[#77735F] mt-1">
              Register a lecture hall or lab for session timetables.
            </p>

            {formError && (
              <div className="mt-3 p-2.5 bg-red-50 border border-red-200 rounded-xl text-xs text-red-600">
                {formError}
              </div>
            )}

            <form onSubmit={handleCreate} className="mt-4 space-y-3.5">
              <div>
                <label className="block text-xs font-semibold text-[#77735F] mb-1">
                  Room ID (e.g. A-201, LAB-01)
                </label>
                <input
                  type="text"
                  required
                  value={roomId}
                  onChange={(e) => setRoomId(e.target.value)}
                  placeholder="A-201"
                  className="w-full bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3.5 py-2 text-sm text-[#24251C] focus:outline-none focus:border-[#3F451F]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#77735F] mb-1">
                  Room Name / Description
                </label>
                <input
                  type="text"
                  required
                  value={roomName}
                  onChange={(e) => setRoomName(e.target.value)}
                  placeholder="Advanced Computing Lab 2"
                  className="w-full bg-[#F2EDE0] border border-[#E4DDCA] rounded-xl px-3.5 py-2 text-sm text-[#24251C] focus:outline-none focus:border-[#3F451F]"
                />
              </div>

              <div className="pt-3 flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  className="px-4 py-2 rounded-xl text-sm font-semibold text-[#77735F] hover:bg-[#F2EDE0] transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 rounded-xl text-sm font-semibold bg-[#3F451F] text-[#FBF8F0] hover:bg-[#323719] transition-colors disabled:opacity-50"
                >
                  {isSubmitting ? "Creating..." : "Save Room"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
