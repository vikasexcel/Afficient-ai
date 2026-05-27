import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { Switch } from "@/components/ui/switch";

export default function AppearanceCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Appearance
        </CardTitle>
      </CardHeader>

      <CardContent>
        <div className="flex justify-between">
          <span>
            Dark Mode
          </span>

          <Switch />
        </div>
      </CardContent>
    </Card>
  );
}