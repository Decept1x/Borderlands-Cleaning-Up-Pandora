import unrealsdk # type: ignore
import random
from Mods import ModMenu # type: ignore
from unrealsdk import Log, FindObject, KeepAlive, ConstructObject, GetEngine # type: ignore
from collections import namedtuple

class CleaningUpPandora(ModMenu.SDKMod):
    Name: str = "Cleaning Up Pandora"
    Author: str = "Deceptix_"
    Description: str = ("Adds the ability to sell items that are on the floor or in your backpack by pressing the 'Secondary Use' key.\n\n"
                        "NOTE:\n<ul><li>Items that are favorited or equipped cannot be sold.</li>"
                        "<li>Controller users need to press 'Start' to sell items from their backpack</li>"
                        "<li>All sold items can be bought back from any vendor.</li></ul>")
    Version: str = "1.1.0"
    SupportedGames: ModMenu.Game = ModMenu.Game.BL2 | ModMenu.Game.TPS
    Types: ModMenu.ModTypes = ModMenu.ModTypes.Utility
    SaveEnabledState: ModMenu.EnabledSaveType = ModMenu.EnabledSaveType.LoadWithSettings

    Keybinds = [
        ModMenu.Keybind("Sell Backpack Item", "None", IsHidden = True)
    ]

    def __init__(self) -> None:
        self.useCustomKey = ModMenu.Options.Boolean(
            Caption = "Custom Sell Backpack Item Key",
            Description = "Allows you to set a custom keybind for selling an item from your backpack.",
            StartingValue = False,
            Choices = ["No", "Yes"]  # False, True
        )
        
        self.Options = [
            self.useCustomKey
        ]

    def ModOptionChanged(self, option: ModMenu.Options.Base, new_value) -> None:
        if option == self.useCustomKey:
            if new_value is True:
                self.Keybinds[0].IsHidden = False
            else:
                self.Keybinds[0].IsHidden = True

    sellAudio = None
    canSwap = True
    cashAmount = 0

    @ModMenu.Hook("WillowGame.WillowPlayerController.SawPickupable")
    def InitializeFromDefinition(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        if self.isClient(caller): # Removes functionality when the user is not the host
            return True

        base_icon = FindObject("InteractionIconDefinition", "GD_InteractionIcons.Default.Icon_DefaultUse")
        icon = ConstructObject(
                    Class=base_icon.Class,
                    Outer=base_icon.Outer,
                    Name="SecondaryUse",
                    Template=base_icon,
                )
        KeepAlive(icon)
        icon.Icon = 4 # Dollar sign icon
        caller.ServerRCon(f"set {caller.PathName(icon)} Action UseSecondary")
        caller.ServerRCon(f"set {caller.PathName(icon)} Text SELL ITEM")
        
        # Instead of using the Structs mod, we create the tuple ourselves to use in place of the structure
        InteractionIconWithOverrides = namedtuple('InteractionIconWithOverrides',
                                                  ['IconDef', 'OverrideIconDef', 'bOverrideIcon', 'bOverrideAction', 'bOverrideText', 'bCostsToUse', 'CostsCurrencyType', 'CostsAmount'],
                                                  defaults=[None, None, False, False, False, 0, 0, 0])
        
        seenItemType = params.Pickup.ObjectPointer.Inventory.Class.Name
        self.cashAmount = params.Pickup.ObjectPointer.Inventory.MonetaryValue

        if seenItemType != "WillowUsableItem" and seenItemType != "WillowMissionItem": # Checks the type of item the player is looking at to make sure its something sellable
            hudMovie = caller.GetHUDMovie()
            if hudMovie == None: # This fixes an error that is caused when looking at a pickupable directly after closing the inventory
                return True
            hudMovie.ShowToolTip(InteractionIconWithOverrides(IconDef = icon), 1) # Show the tooltip in the hud
            if caller.PlayerInput.bUsingGamepad is True:
                self.canSwap = False # Because the Secondary Use Key on controller is the same as swap weapons, we need to restrict the ability to swap when looking at a pickupable object
        return True

    @ModMenu.Hook("WillowGame.WillowPlayerController.PerformedSecondaryUseAction")
    def onUse(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        inventoryManager = caller.GetPawnInventoryManager()

        if self.isClient(caller): # Disables selling off the floor if you are not the host
            return True

        seenItem = caller.CurrentSeenPickupable.ObjectPointer
        if seenItem == None: # If the player is looking at nothing, we do nothing
            return True
        seenItemType = seenItem.Inventory.Class.Name
        
        if seenItemType != "WillowUsableItem" and seenItemType != "WillowMissionItem": # Checks the type of item the player is looking at to make sure its something sellable
            if seenItem.bPickupable == True and seenItem.bIsMissionItem == False:
                seenItem.SetPickupability(False) # Turn off the ability for the player to pick up the item
                seenItem.PickupShrinkDuration = 0.5
                seenItem.BeginShrinking() # Deletes the gun 
                caller.PlayerSoldItem(0, self.cashAmount) # Adds the monetary value of the item to the players current cash amount
                inventoryManager.ClientConditionalIncrementPickupStats(seenItem.Inventory) # Increases Badass Rank pickup stats (Only if the item has not be picked up)
                self.updateBuyBack(inventoryManager, seenItem.Inventory) # Updates the buyback inventory
                self.playSound(caller) # Plays the vendor sell sound
        return True

    @ModMenu.Hook("WillowGame.StatusMenuInventoryPanelGFxObject.SetTooltipText")
    def setTooltipText(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        WPC = GetEngine().GamePlayers[0].Actor

        if caller.bInEquippedView is True: # Only show updated tooltip when looking at the backpack as you cannot delete items that are equipped
            return True

        if WPC.PlayerInput.bUsingGamepad is False:
            result = f"{params.TooltipsText}\n[{self.getSellKey(WPC)}] Sell Item" # Connects the normal tooltip text with our custom text
        if WPC.PlayerInput.bUsingGamepad is True:
            result = f"{params.TooltipsText}\n<IMG src='xbox360_Start' vspace='-3'> Sell Item" # Connects the normal tooltip text with our custom text

        caller.SetTooltipText(result)
        return False
    
    @ModMenu.Hook("WillowGame.StatusMenuInventoryPanelGFxObject.NormalInputKey")
    def onUseBackpack(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        WPC = GetEngine().GamePlayers[0].Actor
        inventoryManager = WPC.GetPawnInventoryManager()

        if WPC.PlayerInput.bUsingGamepad is False:
            if params.ukey != self.getSellKey(WPC): # Looks for Secondary Use Key
                return True
        if WPC.PlayerInput.bUsingGamepad is True:
            if "Start" not in str(params.ukey): # Looks for Start button
                return True
            
        if params.Uevent == 0: # Checks if pressed
            selectedItem = caller.GetSelectedThing() # Gets Willow Definition of selected item in inventory
            if selectedItem is None or caller.bInEquippedView is True or selectedItem.GetMark() == 2:
                caller.ParentMovie.PlayUISound('ResultFailure') # Plays an error sound if player tries to sell an item that is either equipped or favorited
                return True
            
            caller.BackpackPanel.SaveState() # Saves the current index of the item you are hovering
            WPC.PlayerSoldItem(0, selectedItem.GetMonetaryValue()) # Adds the monetary value of the item to the players current cash amount
            inventoryManager.RemoveInventoryFromBackpack(selectedItem) # Deletes the item from your backpack
            caller.FlourishEquip("SOLD") # Displays a confirmation message
            self.updateBuyBack(inventoryManager, selectedItem) # Updates the buyback inventory
            self.playSound(WPC) # Plays the vendor sell sound

            inventoryManager.UpdateBackpackInventoryCount() # Fixes an issue where the player could not pickup guns if they sold an item while their backpack was full
            caller.ParentMovie.RefreshInventoryScreen(True)
            caller.BackpackPanel.RestoreState() # Sets the current selected item to the one of the same index that was saved previously
        return True
    
    @ModMenu.Hook("WillowGame.WillowPlayerController.ClearSeenPickupable")
    def noPickup(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        self.canSwap = True # Allows the player to swap weapons after looking away from a pickupable
        return True
    
    @ModMenu.Hook("WillowGame.WillowPlayerController.NextWeapon")
    def onSwap(self, caller: unrealsdk.UObject, function: unrealsdk.UFunction, params: unrealsdk.FStruct) -> bool:
        return self.canSwap # Controls the players ability to swap weapons

    def playSound(self, WPC) -> None:
        # Took the sell audio search from apple1417's "AltUseVendors" (https://bl-sdk.github.io/mods/AltUseVendors/)
        if self.sellAudio is None:
            self.sellAudio = FindObject("AkEvent", 'Ake_UI.UI_Vending.Ak_Play_UI_Vending_Sell')
            KeepAlive(self.sellAudio)
        WPC.Pawn.PlayAkEvent(self.sellAudio)

    def getSellKey(self, WPC) -> str:
        if self.useCustomKey.CurrentValue is True: # Checks if the user is using a custom sell bind
            return self.Keybinds[0].Key # Returns the custom bind
        else:
            return WPC.PlayerInput.GetKeyForAction("UseSecondary") # Returns the secondary use bind

    def updateBuyBack(self, invManager, item) -> str:
        buyBack = [entry for entry in invManager.BuyBackInventory] # Creates a list of the items currently in your buyback inventory
        buyBack.append(item.CreateClone()) # Creates a clone of the item you just sold and adds it to the buyback list
        if len(buyBack) > 20:
            buyBack.pop(0) # Removes first item in the list once it reaches a length of 20 (default max)
        invManager.BuyBackInventory = buyBack # Replaces the current buyback inventory with the one we created

    def isClient(self, WPC) -> bool:
        # List of all roles and their enums
        # 0 - None
        # 1 - SimulatedProxy
        # 2 - AutonomousProxy
        # 3 - Authority
        # 4 - MAX
        return WPC.Role < 3 # Checks if you are not the host

    def Enable(self) -> None:
        super().Enable()

    def Disable(self) -> None:
        super().Disable()
       
instance = CleaningUpPandora()
ModMenu.RegisterMod(instance)