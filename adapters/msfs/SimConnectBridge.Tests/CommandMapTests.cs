using System.Text.RegularExpressions;
using FluentAssertions;
using Xunit;

namespace SimConnectBridge.Tests;

/// <summary>
/// Guards the SimConnect write surface declared by <c>SimConnectManager.CommandMap</c>.
/// <para>
/// Whatever is in that table is executable; whatever is absent fails silently with an
/// <c>Unknown command</c> log and a <c>success:false</c> ack, which is how four systems
/// already exposed in the <c>set_aircraft_control</c> enum -- trim, de-ice, fuel selector
/// and crossfeed -- came to be reported as actioned while nothing moved (CMD-07).
/// </para>
/// <para>
/// <b>Why these assertions parse source text instead of reading the field.</b>
/// <c>CommandMap</c> is <c>private static readonly</c>, so reflection would normally be the
/// route. It is not available here: reflection requires <c>SimConnectManager.cs</c> to be
/// compiled into this assembly, and both it and <c>Models/SimDataStructs.cs</c>
/// <c>using Microsoft.FlightSimulator.SimConnect</c>. This test project deliberately omits
/// that reference so it builds on runners without the MSFS SDK installed -- see the
/// <c>ItemGroup</c> comment in <c>SimConnectBridge.Tests.csproj</c> and the Phase 06
/// decision to have CI build only this project. Adding the SDK reference to satisfy a test
/// would break CI, so the sources are located relative to the test assembly's base
/// directory and read as text.
/// </para>
/// </summary>
public class CommandMapTests
{
    // -----------------------------------------------------------------------
    //  Source location and parsing
    // -----------------------------------------------------------------------

    /// <summary>Matches a single CommandMap entry: <c>["EVENT_NAME"] = SimEventId.Member,</c>.</summary>
    private static readonly Regex EntryPattern = new(
        @"\[""(?<key>[A-Za-z0-9_]+)""\]\s*=\s*SimEventId\.(?<value>[A-Za-z0-9_]+)\s*,",
        RegexOptions.Compiled);

    private static readonly Lazy<string> AdapterDirectory = new(LocateAdapterDirectory);

    private static readonly Lazy<IReadOnlyList<(string Key, string Value)>> Entries =
        new(ParseCommandMap);

    private static readonly Lazy<IReadOnlySet<string>> DeclaredEventIds = new(ParseSimEventIdMembers);

    /// <summary>
    /// Walks up from the test assembly's base directory until it finds the adapter root --
    /// the directory holding both <c>SimConnectManager.cs</c> and <c>Models/SimDataStructs.cs</c>.
    /// Walking rather than assuming a fixed depth keeps this working under any
    /// configuration/TFM output path.
    /// </summary>
    private static string LocateAdapterDirectory()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            if (File.Exists(Path.Combine(dir.FullName, "SimConnectManager.cs"))
                && File.Exists(Path.Combine(dir.FullName, "Models", "SimDataStructs.cs")))
            {
                return dir.FullName;
            }

            dir = dir.Parent;
        }

        throw new InvalidOperationException(
            "Could not locate the MSFS adapter sources by walking up from " +
            $"'{AppContext.BaseDirectory}'. CommandMapTests reads SimConnectManager.cs and " +
            "Models/SimDataStructs.cs as text because this test project must not take a " +
            "SimConnect SDK reference.");
    }

    /// <summary>Reads every CommandMap entry in declaration order, duplicates included.</summary>
    private static IReadOnlyList<(string Key, string Value)> ParseCommandMap()
    {
        var source = File.ReadAllText(Path.Combine(AdapterDirectory.Value, "SimConnectManager.cs"));
        return EntryPattern.Matches(source)
            .Select(m => (m.Groups["key"].Value, m.Groups["value"].Value))
            .ToList();
    }

    /// <summary>Reads the member names declared by the <c>SimEventId</c> enum.</summary>
    private static IReadOnlySet<string> ParseSimEventIdMembers()
    {
        var source = File.ReadAllText(
            Path.Combine(AdapterDirectory.Value, "Models", "SimDataStructs.cs"));

        var start = source.IndexOf("public enum SimEventId", StringComparison.Ordinal);
        start.Should().BeGreaterThan(-1, "SimDataStructs.cs must declare the SimEventId enum");

        var open = source.IndexOf('{', start);
        var close = source.IndexOf('}', open);
        var body = source[(open + 1)..close];

        var members = new HashSet<string>(StringComparer.Ordinal);
        foreach (var rawLine in body.Split('\n'))
        {
            var line = rawLine;
            var comment = line.IndexOf("//", StringComparison.Ordinal);
            if (comment >= 0) line = line[..comment];

            var name = line.Trim().TrimEnd(',').Trim();
            if (name.Length > 0 && Regex.IsMatch(name, @"^[A-Za-z_][A-Za-z0-9_]*$"))
            {
                members.Add(name);
            }
        }

        return members;
    }

    private static IReadOnlyDictionary<string, string> Map =>
        Entries.Value
            .GroupBy(e => e.Key, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(g => g.Key, g => g.First().Value, StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// The six systems deferred to CMD-09. None may be registered until the authority gate
    /// (plan 02-04) and the procedure re-route (plan 02-07) land -- see D-01.
    /// </summary>
    public static readonly string[] Cmd09EventNames =
    [
        "MAGNETO_SET",
        "ANTI_ICE_CARB_HEAT_TOGGLE",
        "FUEL_PUMP_TOGGLE",
        "TOGGLE_STARTER1",
        "TOGGLE_PRIMER",
        "LANDING_LIGHTS_TOGGLE",
        "TOGGLE_TAXI_LIGHTS",
        "TOGGLE_NAV_LIGHTS",
        "TOGGLE_BEACON_LIGHTS",
        "STROBES_TOGGLE",
        "PANEL_LIGHTS_TOGGLE",
    ];

    /// <summary>Number of entries CommandMap must hold: 36 pre-existing plus the 20 added for CMD-07.</summary>
    private const int ExpectedEntryCount = 56;

    // -----------------------------------------------------------------------
    //  Every event the enum-exposed systems can resolve to has a handler
    // -----------------------------------------------------------------------

    [Theory]
    // Flaps
    [InlineData("FLAPS_UP", "flaps")]
    [InlineData("FLAPS_1", "flaps")]
    [InlineData("FLAPS_2", "flaps")]
    [InlineData("FLAPS_3", "flaps")]
    [InlineData("FLAPS_FULL", "flaps")]
    [InlineData("FLAPS_SET", "flaps")]
    [InlineData("FLAPS_INCR", "flaps")]
    [InlineData("FLAPS_DECR", "flaps")]
    // Gear
    [InlineData("GEAR_TOGGLE", "gear")]
    [InlineData("GEAR_UP", "gear")]
    [InlineData("GEAR_DOWN", "gear")]
    // Autopilot
    [InlineData("AP_MASTER", "autopilot")]
    [InlineData("AP_HDG_HOLD", "autopilot")]
    [InlineData("HEADING_BUG_SET", "autopilot")]
    [InlineData("AP_ALT_HOLD", "autopilot")]
    [InlineData("AP_ALT_VAR_SET_ENGLISH", "autopilot")]
    [InlineData("AP_VS_HOLD", "autopilot")]
    [InlineData("AP_VS_VAR_SET_ENGLISH", "autopilot")]
    [InlineData("AP_AIRSPEED_HOLD", "autopilot")]
    [InlineData("AP_SPD_VAR_SET", "autopilot")]
    [InlineData("AP_NAV1_HOLD", "autopilot")]
    [InlineData("AP_APR_HOLD", "autopilot")]
    // Throttle
    [InlineData("THROTTLE_SET", "throttle")]
    [InlineData("THROTTLE1_SET", "throttle")]
    [InlineData("THROTTLE2_SET", "throttle")]
    // Mixture / propeller
    [InlineData("MIXTURE_SET", "mixture")]
    [InlineData("PROP_PITCH_SET", "propeller")]
    // Radios
    [InlineData("COM_RADIO_SET_HZ", "radio")]
    [InlineData("COM2_RADIO_SET_HZ", "radio")]
    [InlineData("NAV1_RADIO_SET_HZ", "radio")]
    [InlineData("NAV2_RADIO_SET_HZ", "radio")]
    // Barometer / parking brake / spoilers
    [InlineData("KOHLSMAN_SET", "barometer")]
    [InlineData("PARKING_BRAKES", "parking_brake")]
    [InlineData("SPOILERS_TOGGLE", "spoilers")]
    [InlineData("SPOILERS_SET", "spoilers")]
    // Trim
    [InlineData("ELEVATOR_TRIM_SET", "trim")]
    [InlineData("ELEV_TRIM_UP", "trim")]
    [InlineData("ELEV_TRIM_DN", "trim")]
    [InlineData("RUDDER_TRIM_LEFT", "trim")]
    [InlineData("RUDDER_TRIM_RIGHT", "trim")]
    [InlineData("RUDDER_TRIM_SET", "trim")]
    [InlineData("AILERON_TRIM_LEFT", "trim")]
    [InlineData("AILERON_TRIM_RIGHT", "trim")]
    [InlineData("AILERON_TRIM_SET", "trim")]
    // De-ice
    [InlineData("PITOT_HEAT_TOGGLE", "deice")]
    [InlineData("TOGGLE_STRUCTURAL_DEICE", "deice")]
    [InlineData("WINDSHIELD_DEICE_TOGGLE", "deice")]
    [InlineData("TOGGLE_PROPELLER_DEICE", "deice")]
    // Fuel selector
    [InlineData("FUEL_SELECTOR_OFF", "fuel_selector")]
    [InlineData("FUEL_SELECTOR_ALL", "fuel_selector")]
    [InlineData("FUEL_SELECTOR_LEFT", "fuel_selector")]
    [InlineData("FUEL_SELECTOR_RIGHT", "fuel_selector")]
    [InlineData("FUEL_SELECTOR_SET", "fuel_selector")]
    // Crossfeed
    [InlineData("CROSS_FEED_OPEN", "crossfeed")]
    [InlineData("CROSS_FEED_OFF", "crossfeed")]
    [InlineData("CROSS_FEED_TOGGLE", "crossfeed")]
    public void CommandMap_ContainsHandlerFor(string eventName, string system)
    {
        Map.Should().ContainKey(eventName,
            "the '{0}' system in the set_aircraft_control enum resolves to {1}, and without a " +
            "CommandMap entry ExecuteCommand logs 'Unknown command' and acks success:false " +
            "while MERLIN reports the action as taken",
            system, eventName);
    }

    // -----------------------------------------------------------------------
    //  Structural guards
    // -----------------------------------------------------------------------

    [Fact]
    public void CommandMap_HasExactlyTheExpectedNumberOfEntries()
    {
        Entries.Value.Count.Should().Be(ExpectedEntryCount,
            "the entry count is pinned so that deleting any single CommandMap entry fails the " +
            "suite rather than silently removing a control from the write surface; if this is " +
            "an intentional addition, update ExpectedEntryCount and add an [InlineData] row");
    }

    [Fact]
    public void CommandMap_DoesNotRegisterAnyCmd09Event()
    {
        var registered = Cmd09EventNames.Where(name => Map.ContainsKey(name)).ToList();

        registered.Should().BeEmpty(
            "magnetos, carb_heat, fuel_pump, starter, primer and lights are deferred to CMD-09 " +
            "per D-01. execute_procedure bypasses the set_aircraft_control enum entirely and " +
            "PROCEDURES[\"shutdown\"] contains a magnetos step, so registering MAGNETO_SET " +
            "before the authority gate (plan 02-04) and the procedure re-route (plan 02-07) " +
            "land turns a named tool call into a working in-flight engine shutdown. Found: {0}",
            string.Join(", ", registered));
    }

    [Fact]
    public void CommandMap_MapsEveryCommandToADistinctSimEventId()
    {
        var duplicates = Entries.Value
            .GroupBy(e => e.Value, StringComparer.Ordinal)
            .Where(g => g.Count() > 1)
            .Select(g => $"{g.Key} <- {string.Join(" / ", g.Select(e => e.Key))}")
            .ToList();

        duplicates.Should().BeEmpty(
            "each command must map to its own SimEventId; a copy-paste duplicate would route " +
            "two different commands to the same MapClientEventToSimEvent registration, so one " +
            "of them would silently actuate the other's control. Found: {0}",
            string.Join("; ", duplicates));
    }

    [Fact]
    public void CommandMap_OnlyReferencesDeclaredSimEventIdMembers()
    {
        var undeclared = Entries.Value
            .Select(e => e.Value)
            .Where(v => !DeclaredEventIds.Value.Contains(v))
            .Distinct(StringComparer.Ordinal)
            .ToList();

        undeclared.Should().BeEmpty(
            "every CommandMap value must be a member of the SimEventId enum in " +
            "Models/SimDataStructs.cs; this assertion is the compile check this project " +
            "cannot perform directly, because taking a SimConnect SDK reference would break " +
            "CI runners without the MSFS SDK. Found: {0}",
            string.Join(", ", undeclared));
    }

    [Fact]
    public void SimEventIdEnum_DeclaresNoCmd09Members()
    {
        string[] cmd09Members =
        [
            "MagnetoSet", "CarbHeatToggle", "FuelPumpToggle", "StarterToggle", "PrimerToggle",
            "LandingLightsToggle", "TaxiLightsToggle", "NavLightsToggle", "BeaconLightsToggle",
            "StrobesToggle", "PanelLightsToggle",
        ];

        var declared = cmd09Members.Where(m => DeclaredEventIds.Value.Contains(m)).ToList();

        declared.Should().BeEmpty(
            "the CMD-09 systems must stay out of the enum as well as out of CommandMap, so the " +
            "deferral in D-01 cannot be undone by a one-line map edit. Found: {0}",
            string.Join(", ", declared));
    }
}
