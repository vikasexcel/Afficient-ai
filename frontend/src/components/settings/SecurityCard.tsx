import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { Button } from "@/components/ui/button";

export default function SecurityCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Security
        </CardTitle>
      </CardHeader>

      <CardContent>
        <Button variant="destructive">
          Logout All Sessions
        </Button>
      </CardContent>
    </Card>
  );
}