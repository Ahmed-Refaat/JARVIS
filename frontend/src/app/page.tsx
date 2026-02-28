"use client";

import { useState } from "react";

import { Corkboard } from "@/components/Corkboard";
import { DossierView } from "@/components/DossierView";
import { LiveFeed } from "@/components/LiveFeed";
import { StatusBar } from "@/components/StatusBar";
import { TopBar } from "@/components/TopBar";
import { useSpecterData } from "@/hooks/useSpecterData";

export default function Home() {
  const { persons, connections, activity, isLive } = useSpecterData();
  const [selectedPersonId, setSelectedPersonId] = useState<string | null>(persons[0]?._id ?? null);

  const selectedPerson = persons.find((person) => person._id === selectedPersonId) ?? null;

  return (
    <div className="h-screen w-screen overflow-hidden flex flex-col" style={{ background: "var(--bg-dark)" }}>
      <TopBar personCount={persons.length} isLive={isLive} />

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 relative">
          <Corkboard
            persons={persons}
            connections={connections}
            onPersonClick={(id) => setSelectedPersonId(id)}
            selectedPersonId={selectedPersonId}
          />
        </div>

        <LiveFeed activity={activity} onEventClick={(personId) => setSelectedPersonId(personId ?? null)} />

        {selectedPerson && (
          <DossierView
            person={selectedPerson}
            onClose={() => setSelectedPersonId(null)}
          />
        )}
      </div>

      <StatusBar persons={persons} />
    </div>
  );
}
