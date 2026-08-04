# Deferred items found during 02-02

Plan-scoped file name (rather than the shared `deferred-items.md`) because plans in this
phase execute in parallel worktrees and an add/add conflict on a shared new file is
gratuitous. Fold into a phase-level list at merge if wanted.

## 15 pre-existing failures in the C# test suite

Present on the base commit (`d7e6fef`), unchanged by this plan. Baseline was
115 passed / 15 failed / 130 total; after this plan it is 176 passed / 15 failed / 191 total.
The same 15 fail before and after. Out of scope per the executor scope boundary — logged, not
fixed.

| Test | Cases | Cause |
|---|---|---|
| `SimDataStructTests.AllStructs_HaveSequentialLayout` | 4 | `StructLayoutAttribute` is a *pseudo-custom attribute*: the compiler folds it into type metadata flags and `Type.GetCustomAttributes` does not return it. The assertion can never pass as written. `Type.StructLayoutAttribute` is the property that actually reads it back. |
| `SimDataStructTests.AllStructs_UsePack1` | 4 | Same root cause. |
| `SimDataStructTests.AllStructs_UseAnsiCharSet` | 4 | Same root cause. |
| `SimDataStructTests.LowFrequencyData_HasCorrectSize` | 1 | Asserts 136 bytes (2 int + 16 double); actual is 144. |
| `SimDataStructTests.LowFrequencyData_Has18Fields` | 1 | Asserts 18 fields; `TestDataStructs.LowFrequencyData` declares 19. |
| `SimStateSerializationTests.Deserialize_MinimalJson_CreatesValidObject` | 1 | Not investigated — unrelated to the command surface. |

The two `LowFrequencyData` failures are worth flagging to whoever picks this up: the plan
warned that `SimDataStructTests.cs` hard-codes the field count and that `LowFrequencyData`
must not be touched. The hard-coded count is **already wrong** on `main` — the mirror struct in
`TestDataStructs.cs` has 19 fields and the test asserts 18. So the guard the plan was
protecting is not currently guarding anything. Any future plan that does need to add a
low-frequency simvar should fix these first, or it will not get the warning it expects.

Suggested owner: a housekeeping plan, not Phase 2 authority work.

## Test project does not compile the files it tests

`SimConnectBridge.Tests.csproj` compiles only `Models/SimState.cs` and
`TelemetryServiceClient.cs`. `SimConnectManager.cs` and `Models/SimDataStructs.cs` are excluded
because they `using Microsoft.FlightSimulator.SimConnect`, which CI runners do not have.

Consequence: `dotnet build SimConnectBridge.Tests.csproj` passing proves nothing about those
two files. During this plan the changes were compile-checked by building
`SimConnectBridge.csproj` on a machine that does have the MSFS SDK — CI cannot do that.

`CommandMapTests.cs` works around this by parsing both files as source text, and its
`CommandMap_OnlyReferencesDeclaredSimEventIdMembers` assertion is a deliberate substitute for
the compile check. That covers CommandMap specifically; it does not cover the rest of
`SimConnectManager.cs`.

A durable fix would be to extract `CommandMap` (and the `SimEventId` enum) into a file with no
SimConnect SDK dependency and compile *that* into the test project. Deferred: it touches the
adapter's file layout, which is more than CMD-07 warrants.
